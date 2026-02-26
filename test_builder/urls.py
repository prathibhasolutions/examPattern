from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='builder_dashboard'),
    path('search-suggestions/', views.search_suggestions, name='builder_search_suggestions'),
    path('series/', views.manage_series, name='builder_manage_series'),
    path('create/', views.create_test, name='builder_create_test'),
    path('<int:draft_id>/sections/', views.manage_sections, name='manage_sections'),
    path('<int:draft_id>/section/<int:section_id>/questions/', views.manage_questions, name='manage_questions'),
    path('<int:draft_id>/publish/', views.publish_test, name='builder_publish_test'),
    path('<int:draft_id>/delete/', views.delete_draft, name='builder_delete_draft'),
    path('<int:draft_id>/unpublish/', views.unpublish_test, name='builder_unpublish_test'),
    path('<int:draft_id>/delete-published/', views.delete_published_test, name='builder_delete_published'),
    path('<int:draft_id>/toggle-active/', views.toggle_test_active, name='builder_toggle_active'),
]
