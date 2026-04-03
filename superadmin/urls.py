from django.urls import path
from . import views

app_name = 'superadmin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Users
    path('users/', views.user_list, name='user_list'),
    path('users/<int:user_id>/role/', views.user_update_role, name='user_update_role'),
    path('users/<int:user_id>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),

    # Series
    path('series/', views.series_list, name='series_list'),
    path('series/<int:series_id>/toggle/', views.series_toggle_active, name='series_toggle'),
    path('series/<int:series_id>/delete/', views.series_delete, name='series_delete'),

    # Tests
    path('tests/', views.test_list, name='test_list'),
    path('tests/<int:test_id>/toggle/', views.test_toggle_active, name='test_toggle'),
    path('tests/<int:test_id>/delete/', views.test_delete, name='test_delete'),
]
