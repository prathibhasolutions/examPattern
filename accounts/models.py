from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.utils import timezone
import secrets
import random
import string


def _generate_uid(year):
    """Generate UID: EXP + 4-digit year + 4 random uppercase alphanumeric chars"""
    chars = string.ascii_uppercase + string.digits
    return 'EXP' + str(year) + ''.join(random.choices(chars, k=4))

class CustomUser(AbstractUser):
    """Custom user model with email, mobile, and photo"""
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=15, blank=True, help_text="Enter 10 digit mobile number")
    photo = models.ImageField(
        upload_to='user_photos/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png'])],
        help_text="JPG or PNG, max 100KB"
    )
    is_verified = models.BooleanField(default=False, help_text="Email verified status")
    active_session_key = models.CharField(max_length=40, null=True, blank=True)
    uid = models.CharField(max_length=11, unique=True, null=True, blank=True, db_index=True,
                           help_text="Unique user ID in format EXP{YEAR}{4 chars}, e.g. EXP2026A3F9")
    has_legacy_access = models.BooleanField(
        default=False,
        help_text="If True, user has unlimited access to all test series without payment. "
                  "Set automatically for all accounts created before the paywall was introduced."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def save(self, *args, **kwargs):
        if not self.uid:
            year = timezone.now().year
            for _ in range(30):
                candidate = _generate_uid(year)
                if not CustomUser.objects.filter(uid=candidate).exclude(pk=self.pk or 0).exists():
                    self.uid = candidate
                    break
        super().save(*args, **kwargs)

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


class ForgotPasswordRequest(models.Model):
    """Tracks user requests to have their password reset by a superadmin."""
    STATUS_PENDING = 'pending'
    STATUS_RESOLVED = 'resolved'
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('resolved', 'Resolved'),
    ]

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='password_requests'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_password_requests'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Password request by {self.user.username} ({self.status})"

    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_used and timezone.now() < self.expires_at
