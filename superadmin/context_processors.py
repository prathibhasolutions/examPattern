from accounts.models import ForgotPasswordRequest


def pending_pw_requests(request):
    """Inject pending password request count into every superadmin template."""
    if request.user.is_authenticated and request.user.is_superuser:
        count = ForgotPasswordRequest.objects.filter(status='pending').count()
    else:
        count = 0
    return {'pending_pw_count': count}
