"""
Middleware to exempt API endpoints from CSRF protection
"""
from django.utils.deprecation import MiddlewareMixin


class CSRFExemptAPIMiddleware(MiddlewareMixin):
    """Exempt /api/ endpoints from CSRF protection"""
    
    def process_request(self, request):
        if request.path.startswith('/api/'):
            # Mark the request as exempt from CSRF
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None
