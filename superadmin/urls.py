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
    path('users/<int:user_id>/toggle-legacy/', views.series_access_toggle_legacy, name='toggle_legacy_access'),

    # Password reset requests
    path('password-requests/', views.password_requests, name='password_requests'),
    path('password-requests/<int:req_id>/resolve/', views.resolve_password_request, name='resolve_password_request'),

    # Series
    path('series/', views.series_list, name='series_list'),
    path('series/<int:series_id>/toggle/', views.series_toggle_active, name='series_toggle'),
    path('series/<int:series_id>/delete/', views.series_delete, name='series_delete'),

    # Tests
    path('tests/', views.test_list, name='test_list'),
    path('tests/<int:test_id>/toggle/', views.test_toggle_active, name='test_toggle'),
    path('tests/<int:test_id>/delete/', views.test_delete, name='test_delete'),

    # Series pricing
    path('series-pricing/', views.series_pricing, name='series_pricing'),
    path('series-pricing/<int:series_id>/set-price/', views.series_set_price, name='series_set_price'),

    # Series access management
    path('series-access/', views.series_access, name='series_access'),
    path('series-access/grant/', views.series_access_grant, name='series_access_grant'),
    path('series-access/<int:access_id>/revoke/', views.series_access_revoke, name='series_access_revoke'),

    # Series plans (flexible pricing)
    path('series-plans/<int:series_id>/', views.series_plans, name='series_plans'),
    path('series-plans/<int:series_id>/add/', views.series_plan_add, name='series_plan_add'),
    path('series-plans/plan/<int:plan_id>/toggle/', views.series_plan_toggle, name='series_plan_toggle'),
    path('series-plans/plan/<int:plan_id>/delete/', views.series_plan_delete, name='series_plan_delete'),
]
