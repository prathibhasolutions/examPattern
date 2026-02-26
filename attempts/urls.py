from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import TestAttemptViewSet

router = DefaultRouter()
router.register(r'attempts', TestAttemptViewSet, basename='attempt')

urlpatterns = [
    path('', include(router.urls)),
]
