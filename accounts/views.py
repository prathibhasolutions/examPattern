from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os
import re
from .models import CustomUser
from .forms import RegistrationForm, LoginForm


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Login page — manual email/password or Google OAuth."""
    if request.user.is_authenticated:
        return redirect('tests_list')

    form = LoginForm()

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].lower()
            password = form.cleaned_data['password']
            try:
                user_obj = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                user_obj = None

            if user_obj is not None:
                user = authenticate(request, username=user_obj.username, password=password)
            else:
                user = None

            if user is not None:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect(request.GET.get('next') or 'tests_list')
            else:
                messages.error(request, 'Invalid email or password.')

    return render(request, 'accounts/login.html', {'form': form})


@require_http_methods(["GET", "POST"])
def register_view(request):
    """Registration page — manual sign-up."""
    if request.user.is_authenticated:
        return redirect('tests_list')

    form = RegistrationForm()

    if request.method == 'POST':
        form = RegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            email = form.cleaned_data['email']
            username = form.cleaned_data['username']
            mobile = form.cleaned_data['mobile']
            password = form.cleaned_data['password']
            photo = form.cleaned_data.get('photo')

            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                mobile=mobile,
                is_verified=False,
            )

            if photo:
                try:
                    img = Image.open(photo)
                    img.verify()
                    photo.seek(0)
                    img = Image.open(photo)
                    if img.mode == 'RGBA':
                        bg = Image.new('RGB', img.size, (255, 255, 255))
                        bg.paste(img, mask=img.split()[3])
                        img = bg
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    img.save(output, format='JPEG', quality=85, optimize=True)
                    output.seek(0)
                    user.photo.save(
                        f"user_{user.id}_{photo.name}",
                        ContentFile(output.read()),
                        save=True,
                    )
                except Exception:
                    pass  # photo upload failure is non-fatal

            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, f'Welcome to examPattern, {user.username}!')
            return redirect('tests_list')

    return render(request, 'accounts/register.html', {'form': form})


@login_required(login_url='login')
def profile(request):
    """User profile view"""
    from attempts.models import TestAttempt
    from django.db.models import Max

    user = request.user

    if request.method == 'POST':
        new_username = request.POST.get('username', '').strip()
        new_mobile = request.POST.get('mobile', '').strip()
        has_error = False

        if new_username and new_username != user.username:
            if len(new_username) < 3:
                messages.error(request, 'Username must be at least 3 characters.')
                has_error = True
            elif not re.match(r'^[\w.@+-]+$', new_username):
                messages.error(request, 'Username may only contain letters, digits, and @/./+/-/_ characters.')
                has_error = True
            elif CustomUser.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                messages.error(request, 'That username is already taken.')
                has_error = True

        if not has_error and new_mobile != user.mobile:
            if new_mobile and (not new_mobile.isdigit() or len(new_mobile) != 10):
                messages.error(request, 'Mobile number must be exactly 10 digits.')
                has_error = True

        if not has_error:
            if new_username and new_username != user.username:
                user.username = new_username
            if new_mobile != user.mobile:
                user.mobile = new_mobile
            user.save(update_fields=['username', 'mobile'])
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')

    # Get the latest attempt for each test (SQLite compatible)
    latest_attempts = (
        TestAttempt.objects
        .filter(user=user, status=TestAttempt.STATUS_SUBMITTED)
        .values('test')
        .annotate(latest_id=Max('id'))
    )

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
        return JsonResponse({'available': False, 'message': 'Enter a valid email address.'})

    if CustomUser.objects.filter(email=email).exists():
        return JsonResponse({'available': False, 'message': 'An account with this email already exists.'})

    return JsonResponse({'available': True, 'message': 'Email is available!'})


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
