from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import TestSeriesViewSet, TestViewSet

router = DefaultRouter()
router.register(r'series', TestSeriesViewSet, basename='testseries')
router.register(r'tests', TestViewSet, basename='test')

urlpatterns = [
    path('', include(router.urls)),
]
