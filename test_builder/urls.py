from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='builder_dashboard'),
    path('search-suggestions/', views.search_suggestions, name='builder_search_suggestions'),
    path('series/', views.manage_series, name='builder_manage_series'),
    path('create/', views.create_test, name='builder_create_test'),
    path('<int:draft_id>/sections/', views.manage_sections, name='manage_sections'),
    path('<int:draft_id>/section/<int:section_id>/questions/', views.manage_questions, name='manage_questions'),
    path('<int:draft_id>/live-editor/', views.live_editor, name='live_editor'),
    path('<int:draft_id>/import-pdf/', views.import_pdf_to_draft, name='import_pdf_to_draft'),
    path('<int:draft_id>/import-json/', views.import_json_to_draft, name='import_json_to_draft'),
    path('<int:draft_id>/api/section/add/', views.api_add_section, name='api_add_section'),
    path('<int:draft_id>/api/section/<int:section_id>/rename/', views.api_rename_section, name='api_rename_section'),
    path('<int:draft_id>/api/section/<int:section_id>/delete/', views.api_delete_section, name='api_delete_section'),
    path('<int:draft_id>/api/question/save/', views.api_save_question, name='api_save_question'),
    path('<int:draft_id>/api/question/<int:question_id>/delete/', views.api_delete_question, name='api_delete_question'),
    path('<int:draft_id>/api/validate/', views.api_validate_draft, name='api_validate_draft'),
    path('<int:draft_id>/publish/', views.publish_test, name='builder_publish_test'),
    path('<int:draft_id>/delete/', views.delete_draft, name='builder_delete_draft'),
    path('<int:draft_id>/unpublish/', views.unpublish_test, name='builder_unpublish_test'),
    path('<int:draft_id>/delete-published/', views.delete_published_test, name='builder_delete_published'),
    path('<int:draft_id>/toggle-active/', views.toggle_test_active, name='builder_toggle_active'),
    path('orphan/<int:test_id>/deactivate/', views.deactivate_orphaned_test, name='builder_deactivate_orphan'),
]
