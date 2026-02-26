from django import forms
from django.contrib.auth import authenticate
from .models import CustomUser


class RegistrationForm(forms.ModelForm):
    """User registration form with validation"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password (min 8 characters)'
        }),
        min_length=8,
        help_text='Min 8 characters'
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        }),
        label='Confirm Password'
    )

    class Meta:
        model = CustomUser
        fields = ['email', 'username', 'mobile', 'photo']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email address',
                'required': True
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username (unique)',
                'required': True
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Mobile number (10 digits)',
                'pattern': '[0-9]{10}',
                'required': True
            }),
            'photo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/jpeg,image/png',
                'help_text': 'JPG or PNG, max 100KB'
            }),
        }

    def clean_username(self):
        """Check if username is unique"""
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken. Try another one.")
        return username

    def clean_email(self):
        """Check if email is unique"""
        email = self.cleaned_data.get('email').lower()
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def clean_mobile(self):
        """Validate mobile number format"""
        mobile = self.cleaned_data.get('mobile')
        if not mobile.isdigit() or len(mobile) != 10:
            raise forms.ValidationError("Mobile number must be exactly 10 digits.")
        if CustomUser.objects.filter(mobile=mobile).exists():
            raise forms.ValidationError("This mobile number is already registered.")
        return mobile

    def clean_photo(self):
        """Validate photo size (max 100KB)"""
        photo = self.cleaned_data.get('photo')
        if photo:
            if photo.size > 100 * 1024:  # 100KB in bytes
                raise forms.ValidationError("Photo size must be less than 100KB.")
        return photo

    def clean(self):
        """Check password confirmation"""
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', 'Passwords do not match.')
        return cleaned_data

    def save(self, commit=True):
        """Hash password before saving"""
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """User login form"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username or Email',
            'autofocus': True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Remember me'
    )

    def clean(self):
        """Authenticate user credentials"""
        cleaned_data = super().clean()
        username_or_email = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username_or_email and password:
            # Try to authenticate with username first, then email
            user = authenticate(username=username_or_email, password=password)
            if not user:
                # Try with email
                try:
                    user_obj = CustomUser.objects.get(email=username_or_email)
                    user = authenticate(username=user_obj.username, password=password)
                except CustomUser.DoesNotExist:
                    user = None

            if not user:
                raise forms.ValidationError("Invalid username/email or password.")
        return cleaned_data


class ForgotPasswordForm(forms.Form):
    """Form for requesting password reset"""
    email_or_mobile = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Enter your email or mobile number',
            'autofocus': True
        }),
        label='Email or Mobile Number'
    )

    def clean_email_or_mobile(self):
        """Verify email or mobile exists"""
        email_or_mobile = self.cleaned_data.get('email_or_mobile').strip()
        
        # Try to find user by email
        user = CustomUser.objects.filter(email=email_or_mobile).first()
        
        # If not found by email, try mobile
        if not user:
            user = CustomUser.objects.filter(mobile=email_or_mobile).first()
        
        if not user:
            raise forms.ValidationError("No account found with this email or mobile number.")
        
        return email_or_mobile


class ResetPasswordForm(forms.Form):
    """Form for resetting password with token"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'New Password (min 8 characters)',
            'autofocus': True
        }),
        min_length=8,
        label='New Password',
        help_text='Min 8 characters'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Confirm Password'
        }),
        label='Confirm Password'
    )

    def clean(self):
        """Check password confirmation"""
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data
