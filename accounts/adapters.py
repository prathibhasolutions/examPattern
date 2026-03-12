from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter for social (Google) login.
    - Auto-generates a unique username from the user's email.
    - Marks the account as verified (Google already verifies email).
    - Leaves mobile blank (user can fill it in via profile settings later).
    """

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        User = get_user_model()

        # Auto-generate a unique username from the Google email if not provided
        if not getattr(user, 'username', None):
            email = data.get('email', '')
            base = email.split('@')[0].lower() if email else 'user'
            # Strip non-alphanumeric characters (except _ and .)
            base = ''.join(c for c in base if c.isalnum() or c in ('_', '.'))[:20] or 'user'
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}{counter}"
                counter += 1
            user.username = username

        # Google emails are already verified
        user.is_verified = True
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # Ensure mobile is empty string for OAuth users (they can set it later)
        if not user.mobile:
            user.mobile = ''
        user.is_verified = True
        user.save(update_fields=['is_verified', 'mobile'])
        return user
