import re
from django import forms
from .models import CustomUser


class RegistrationForm(forms.Form):
    email = forms.EmailField()
    username = forms.CharField(min_length=3, max_length=150)
    mobile = forms.CharField(max_length=10)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput)
    photo = forms.ImageField(required=False)

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        if not re.match(r'^[\w.@+-]+$', username):
            raise forms.ValidationError(
                'Username may only contain letters, digits and @/./+/-/_ characters.'
            )
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError('That username is already taken.')
        return username

    def clean_mobile(self):
        mobile = self.cleaned_data['mobile']
        if not mobile.isdigit() or len(mobile) != 10:
            raise forms.ValidationError('Enter a valid 10-digit mobile number.')
        return mobile

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('password_confirm')
        if password and confirm and password != confirm:
            self.add_error('password_confirm', 'Passwords do not match.')
        return cleaned_data


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

