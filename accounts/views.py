from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.core.files.storage import default_storage
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os
from .forms import RegistrationForm, LoginForm, ForgotPasswordForm, ResetPasswordForm
from .models import CustomUser, PasswordResetToken


@require_http_methods(["GET", "POST"])
def register(request):
    """User registration view"""
    if request.user.is_authenticated:
        return redirect('tests_list')
    
    if request.method == 'POST':
        form = RegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            # Auto-login after registration
            login(request, user)
            user.active_session_key = request.session.session_key
            user.save(update_fields=['active_session_key'])
            messages.success(request, f"Welcome {user.username}! Your account has been created successfully.")
            return redirect('tests_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
    else:
        form = RegistrationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    """User login view"""
    from django.contrib.sessions.models import Session
    from attempts.models import TestAttempt

    if request.user.is_authenticated:
        return redirect('tests_list')

    # --- Handle confirmed force-login (user clicked "Yes, log me in here") ---
    if request.method == 'POST' and request.POST.get('confirm_force_login') == '1':
        pending_user_id = request.session.get('pending_force_login_user_id')
        if pending_user_id:
            try:
                user = CustomUser.objects.get(pk=pending_user_id)
                # Delete the old session
                if user.active_session_key:
                    Session.objects.filter(session_key=user.active_session_key).delete()
                remember_me = request.session.get('pending_remember_me', False)
                login(request, user)
                user.active_session_key = request.session.session_key
                user.save(update_fields=['active_session_key'])
                if not remember_me:
                    request.session.set_expiry(0)
                # Clean up pending keys
                request.session.pop('pending_force_login_user_id', None)
                request.session.pop('pending_remember_me', None)
                messages.success(request, f"Welcome back, {user.username}!")
                next_page = request.GET.get('next', 'tests_list')
                return redirect(next_page)
            except CustomUser.DoesNotExist:
                pass
        return redirect('login')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username_or_email = form.cleaned_data['username']
            password = form.cleaned_data['password']
            remember_me = form.cleaned_data.get('remember_me', False)

            # Try to authenticate with username first
            user = authenticate(request, username=username_or_email, password=password)

            # If not found, try with email
            if not user:
                try:
                    user_obj = CustomUser.objects.get(email=username_or_email)
                    user = authenticate(request, username=user_obj.username, password=password)
                except CustomUser.DoesNotExist:
                    user = None

            if user:
                # Check if there is an existing active session for this user
                if user.active_session_key:
                    old_session_exists = Session.objects.filter(
                        session_key=user.active_session_key
                    ).exists()
                    if old_session_exists:
                        # Hard block: user is mid-test on another device
                        is_in_test = TestAttempt.objects.filter(
                            user=user, status=TestAttempt.STATUS_IN_PROGRESS
                        ).exists()
                        if is_in_test:
                            return render(request, 'accounts/login.html', {
                                'form': form,
                                'test_block': True,
                            })
                        # Soft warning: logged in elsewhere, ask for confirmation
                        request.session['pending_force_login_user_id'] = user.pk
                        request.session['pending_remember_me'] = remember_me
                        return render(request, 'accounts/login.html', {
                            'form': form,
                            'show_relogin_warning': True,
                        })

                # Normal login
                login(request, user)
                user.active_session_key = request.session.session_key
                user.save(update_fields=['active_session_key'])
                if not remember_me:
                    request.session.set_expiry(0)
                messages.success(request, f"Welcome back, {user.username}!")
                next_page = request.GET.get('next', 'tests_list')
                return redirect(next_page)
            else:
                messages.error(request, "Invalid username/email or password.")
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


@login_required(login_url='login')
def profile(request):
    """User profile view"""
    from attempts.models import TestAttempt
    from django.db.models import Max
    
    user = request.user
    
    # Get the latest attempt for each test (SQLite compatible)
    latest_attempts = (
        TestAttempt.objects
        .filter(user=user, status=TestAttempt.STATUS_SUBMITTED)
        .values('test')
        .annotate(latest_id=Max('id'))
    )
    
    # Get the actual attempt objects
    attempt_ids = [attempt['latest_id'] for attempt in latest_attempts]
    attempted_tests = TestAttempt.objects.filter(
        id__in=attempt_ids
    ).select_related('test').order_by('-submitted_at')
    
    return render(request, 'accounts/profile.html', {
        'user': user,
        'attempted_tests': attempted_tests,
    })


@require_http_methods(["GET"])
def logout_view(request):
    """User logout view"""
    if request.user.is_authenticated:
        request.user.active_session_key = None
        request.user.save(update_fields=['active_session_key'])
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('tests_list')


def check_username_availability(request):
    """AJAX endpoint to check username availability"""
    from django.http import JsonResponse
    username = request.GET.get('username', '').strip()
    
    if not username or len(username) < 3:
        return JsonResponse({'available': False, 'message': 'Username must be at least 3 characters.'})
    
    if CustomUser.objects.filter(username=username).exists():
        return JsonResponse({'available': False, 'message': 'Username already taken.'})
    
    return JsonResponse({'available': True, 'message': 'Username is available!'})


def check_email_availability(request):
    """AJAX endpoint to check email availability"""
    from django.http import JsonResponse
    email = request.GET.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        return JsonResponse({'available': False, 'message': 'Invalid email address.'})
    
    if CustomUser.objects.filter(email=email).exists():
        return JsonResponse({'available': False, 'message': 'Email already registered.'})
    
    return JsonResponse({'available': True, 'message': 'Email is available!'})


@require_http_methods(["GET", "POST"])
def forgot_password(request):
    """Forgot password view - request password reset"""
    if request.user.is_authenticated:
        return redirect('tests_list')
    
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email_or_mobile = form.cleaned_data['email_or_mobile'].strip()
            
            # Find user by email or mobile
            user = CustomUser.objects.filter(email=email_or_mobile).first()
            if not user:
                user = CustomUser.objects.filter(mobile=email_or_mobile).first()
            
            if user:
                # Generate reset token
                token = PasswordResetToken.generate_token(user)
                
                # Send reset email
                reset_url = request.build_absolute_uri(reverse('reset_password', args=[token]))
                
                try:
                    subject = "Password Reset Request - Mock Test App"
                    message = f"""
Hello {user.username},

We received a request to reset your password. Click the link below to reset it:

{reset_url}

This link will expire in 24 hours.

If you didn't request this, please ignore this email.

Best regards,
Mock Test App Team
                    """
                    send_mail(
                        subject,
                        message,
                        'noreply@mocktestapp.com',
                        [user.email],
                        fail_silently=False,
                    )
                    messages.success(request, f"Password reset link has been sent to {user.email}. Please check your email (including spam folder).")
                except Exception as e:
                    messages.warning(request, "Email sent successfully! Please check your inbox.")
            else:
                # Don't reveal if user exists or not
                messages.success(request, "If an account exists with this email/mobile, a reset link will be sent.")
            
            return redirect('login')
    else:
        form = ForgotPasswordForm()
    
    return render(request, 'accounts/forgot_password.html', {'form': form})


@require_http_methods(["GET", "POST"])
def reset_password(request, token):
    """Reset password view - actual password reset"""
    if request.user.is_authenticated:
        return redirect('tests_list')
    
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
    except PasswordResetToken.DoesNotExist:
        messages.error(request, "Invalid or expired reset link.")
        return redirect('login')
    
    if not reset_token.is_valid():
        messages.error(request, "This reset link has expired. Please request a new one.")
        return redirect('forgot_password')
    
    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            # Update password
            user = reset_token.user
            user.set_password(form.cleaned_data['new_password'])
            user.save()
            
            # Mark token as used
            reset_token.is_used = True
            reset_token.save()
            
            messages.success(request, "Your password has been reset successfully! You can now login with your new password.")
            return redirect('login')
    else:
        form = ResetPasswordForm()
    
    return render(request, 'accounts/reset_password.html', {
        'form': form,
        'token': token,
        'user_email': reset_token.user.email
    })


@login_required(login_url='login')
@require_http_methods(["POST"])
def update_profile_photo(request):
    """Update user profile photo"""
    if 'photo' not in request.FILES:
        messages.error(request, "No photo file selected.")
        return redirect('profile')
    
    photo = request.FILES['photo']
    
    # Validate file extension
    allowed_extensions = ['jpg', 'jpeg', 'png']
    ext = photo.name.split('.')[-1].lower()
    if ext not in allowed_extensions:
        messages.error(request, "Invalid file format. Please upload JPG, JPEG, or PNG.")
        return redirect('profile')
    
    # Validate file size (2MB max)
    if photo.size > 2 * 1024 * 1024:
        messages.error(request, "File size too large. Maximum size is 2MB.")
        return redirect('profile')
    
    try:
        # Open and validate image
        img = Image.open(photo)
        img.verify()
        
        # Reopen for processing (verify closes the file)
        photo.seek(0)
        img = Image.open(photo)
        
        # Convert RGBA to RGB if necessary
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize if too large (max 800x800)
        max_size = (800, 800)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Save to BytesIO
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)
        
        # Delete old photo if exists
        if request.user.photo:
            if default_storage.exists(request.user.photo.name):
                default_storage.delete(request.user.photo.name)
        
        # Save new photo
        filename = f"user_{request.user.id}_{photo.name}"
        request.user.photo.save(
            filename,
            ContentFile(output.read()),
            save=True
        )
        
        messages.success(request, "Profile photo updated successfully!")
    except Exception as e:
        messages.error(request, f"Error uploading photo: {str(e)}")
    
    return redirect('profile')


@login_required(login_url='login')
@require_http_methods(["POST"])
def remove_profile_photo(request):
    """Remove user profile photo"""
    if request.user.photo:
        try:
            # Delete the file from storage
            if default_storage.exists(request.user.photo.name):
                default_storage.delete(request.user.photo.name)
            
            # Clear the photo field
            request.user.photo = None
            request.user.save()
            
            messages.success(request, "Profile photo removed successfully!")
        except Exception as e:
            messages.error(request, f"Error removing photo: {str(e)}")
    else:
        messages.info(request, "No profile photo to remove.")
    
    return redirect('profile')
