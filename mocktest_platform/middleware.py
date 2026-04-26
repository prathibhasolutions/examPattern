"""
Middleware to exempt API endpoints from CSRF protection
"""
import gzip

from django.http import HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin


class GzipRequestDecompressionMiddleware(MiddlewareMixin):
    """Decompress gzip-encoded JSON request bodies from modern clients."""

    def process_request(self, request):
        encoding = request.META.get('HTTP_CONTENT_ENCODING', '')
        if 'gzip' not in str(encoding).lower():
            return None

        try:
            raw_body = request.body
            request._body = gzip.decompress(raw_body)
            request.META['CONTENT_LENGTH'] = str(len(request._body))
            request.META.pop('HTTP_CONTENT_ENCODING', None)
        except OSError:
            return HttpResponseBadRequest('Invalid gzip request body')

        return None


class CSRFExemptAPIMiddleware(MiddlewareMixin):
    """Exempt /api/ endpoints from CSRF protection"""
    
    def process_request(self, request):
        if request.path.startswith('/api/'):
            # Mark the request as exempt from CSRF
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None
