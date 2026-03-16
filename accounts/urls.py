from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/update-photo/', views.update_profile_photo, name='update_profile_photo'),
    path('profile/remove-photo/', views.remove_profile_photo, name='remove_profile_photo'),
    path('check-username/', views.check_username_availability, name='check_username'),
]
