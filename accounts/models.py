from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.utils import timezone
import secrets

class CustomUser(AbstractUser):
    """Custom user model with email, mobile, and photo"""
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=15, blank=False, help_text="Enter 10 digit mobile number")
    photo = models.ImageField(
        upload_to='user_photos/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])],
        help_text="JPG or PNG, max 100KB"
    )
    is_verified = models.BooleanField(default=False, help_text="Email verified status")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.email})"


class PasswordResetToken(models.Model):
    """Token for password reset via email"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='reset_token')
    token = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"Reset token for {self.user.username}"

    @staticmethod
    def generate_token(user):
        """Generate and save a password reset token"""
        from datetime import timedelta
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(hours=24)
        
        # Delete old token if exists
        PasswordResetToken.objects.filter(user=user).delete()
        
        # Create new token
        reset_token = PasswordResetToken.objects.create(
            user=user,
            token=token,
            expires_at=expires_at
        )
        return token

    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_used and timezone.now() < self.expires_at
