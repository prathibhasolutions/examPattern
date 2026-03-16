from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.conf import settings


@receiver(user_logged_in)
def set_active_session_key(sender, request, user, **kwargs):
    """
    After any login (password-based or Google OAuth), record the new
    session key so multi-device conflict detection keeps working.
    Also ensures Google users are always marked as verified.
    """
    update_fields = []
    new_key = request.session.session_key
    if new_key and user.active_session_key != new_key:
        user.active_session_key = new_key
        update_fields.append('active_session_key')

    # Mark verified if the user has a linked Google account
    if not user.is_verified:
        try:
            from allauth.socialaccount.models import SocialAccount
            if SocialAccount.objects.filter(user=user, provider='google').exists():
                user.is_verified = True
                update_fields.append('is_verified')
        except Exception:
            pass

    if update_fields:
        user.save(update_fields=update_fields)


@receiver(post_migrate)
def update_site_domain(sender, **kwargs):
    """Keep the Django Site record in sync with the SITE_DOMAIN env var."""
    if sender.name != 'django.contrib.sites':
        return
    try:
        from django.contrib.sites.models import Site
        domain = getattr(settings, 'SITE_DOMAIN', 'localhost:8000')
        Site.objects.update_or_create(
            id=settings.SITE_ID,
            defaults={'domain': domain, 'name': domain},
        )
    except Exception:
        pass
