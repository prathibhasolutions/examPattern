"""
URL configuration for mocktest_platform project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

from .views import tests_list, tests_series_detail, tests_series_about, test_instructions, test_interface, results_page, download_result_pdf, review_solutions, test_results_analysis, series_suggest, privacy_policy, terms_of_service, about_page
from django.views.generic import RedirectView

def health_check(request):
    return HttpResponse("OK")

urlpatterns = [
    path('', tests_list, name='home'),
    path('api/v1/series-suggest/', series_suggest, name='series_suggest'),
    path('admin/', admin.site.urls),
    path("health/", health_check),
    path('accounts/', include('accounts.urls')),
    path('oauth/', include('allauth.urls')),  # Google OAuth at /oauth/google/login/callback/
    path('tests/', tests_list, name='tests_list'),
    path('tests/series/<slug:slug>/', tests_series_detail, name='tests_series_detail'),
    path('tests/series/<slug:slug>/about/', tests_series_about, name='tests_series_about'),
    path('test/<int:test_id>/instructions/', test_instructions, name='test_instructions'),
    path('test/<int:test_id>/', test_interface, name='test_interface'),
    path('test/<int:test_id>/results/', test_results_analysis, name='test_results_analysis'),
    path('results/<int:attempt_id>/', results_page, name='results_page'),
    path('results/<int:attempt_id>/download-pdf/', download_result_pdf, name='download_result_pdf'),
    path('results/<int:attempt_id>/solutions/', review_solutions, name='review_solutions'),
    path('about/', about_page, name='about'),
    path('privacy-policy/', privacy_policy, name='privacy_policy'),
    path('terms-of-service/', terms_of_service, name='terms_of_service'),
    path('builder/', include('test_builder.urls')),
    path('superadmin/', include('superadmin.urls')),
    path('api/v1/', include([
        path('', include('testseries.urls')),
        path('', include('attempts.urls')),
    ])),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
