from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction, models
from django.utils.text import slugify
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import logging

from .models import TestDraft, SectionDraft, QuestionDraft, OptionDraft, PDFImportJob
from .services.pdf_import import import_pdf_into_section
from .services.json_import import import_json_into_section
from testseries.models import TestSeries, TestSeriesExamSection, TestSeriesHighlight, Test, Section, SeriesSection, SeriesSubsection
from questions.models import Question, Option

logger = logging.getLogger(__name__)


# Permission check: Only staff users can access builder
def is_admin(user):
    """Check if user has builder (staff) access"""
    return user.is_staff


def admin_required(view_func):
    """Decorator to require builder/admin access"""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_staff:
            return HttpResponseForbidden(
                '<h1>Access Denied</h1><p>You do not have permission to access the test builder. '
                'Only administrators can create and manage tests.</p>'
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def _extract_exam_sections(request):
    sections = []
    try:
        total = int(request.POST.get("exam_section_count", "0"))
    except ValueError:
        total = 0

    for index in range(total):
        title = request.POST.get(f"exam_section_title_{index}", "").strip()
        body = request.POST.get(f"exam_section_body_{index}", "").strip()
        section_id = request.POST.get(f"exam_section_id_{index}", "").strip()
        image = request.FILES.get(f"exam_section_image_{index}")

        if not title and not body and not image:
            continue

        sections.append({
            "id": section_id or None,
            "title": title or "Details",
            "body": body,
            "image": image,
        })

    return sections


def _extract_highlights(request):
    highlights = []
    try:
        total = int(request.POST.get("highlight_count", "0"))
    except ValueError:
        total = 0

    for index in range(total):
        title = request.POST.get(f"highlight_title_{index}", "").strip()
        value = request.POST.get(f"highlight_value_{index}", "").strip()
        highlight_id = request.POST.get(f"highlight_id_{index}", "").strip()

        if not title and not value:
            continue

        highlights.append({
            "id": highlight_id or None,
            "title": title or "Highlight",
            "value": value,
        })

    return highlights[:4]


@admin_required
@login_required
def dashboard(request):
    """Show all drafts and published tests"""
    search_query = request.GET.get('search', '').strip()
    
    # Base querysets
    drafts_qs = TestDraft.objects.filter(created_by=request.user, is_published=False)
    published_qs = TestDraft.objects.filter(created_by=request.user, is_published=True)
    
    # Apply search filter if provided
    if search_query:
        drafts_qs = drafts_qs.filter(
            models.Q(name__icontains=search_query) | 
            models.Q(series__name__icontains=search_query)
        )
        published_qs = published_qs.filter(
            models.Q(name__icontains=search_query) | 
            models.Q(series__name__icontains=search_query)
        )
    
    # Group by series
    from collections import defaultdict
    
    drafts_by_series = defaultdict(list)
    for draft in drafts_qs.select_related('series'):
        drafts_by_series[draft.series].append(draft)
    
    # Fetch all published drafts first to look up matching Test.is_active
    published_drafts = list(published_qs.select_related('series'))
    published_test_ids = [d.published_test_id for d in published_drafts if d.published_test_id]
    test_active_map = dict(
        Test.objects.filter(id__in=published_test_ids).values_list('id', 'is_active')
    )
    published_by_series = defaultdict(list)
    for draft in published_drafts:
        # Annotate draft with the live test's is_active flag for the dashboard toggle
        draft.live_is_active = test_active_map.get(draft.published_test_id, True)
        published_by_series[draft.series].append(draft)

    # Find orphaned active tests: Test objects that are is_active=True but not tracked by any draft
    all_draft_published_ids = set(
        TestDraft.objects.filter(created_by=request.user)
                         .exclude(published_test_id__isnull=True)
                         .values_list('published_test_id', flat=True)
    )
    # Active tests in series that have at least one draft from this user
    user_series_ids = list(TestDraft.objects.filter(created_by=request.user).values_list('series_id', flat=True).distinct())
    orphaned_tests = list(
        Test.objects.filter(is_active=True, series__in=user_series_ids)
                    .exclude(id__in=all_draft_published_ids)
                    .select_related('series')
    )

    # Get all series for suggestions
    all_series = TestSeries.objects.all()
    
    return render(request, 'test_builder/dashboard.html', {
        'drafts_by_series': dict(drafts_by_series),
        'published_by_series': dict(published_by_series),
        'orphaned_tests': orphaned_tests,
        'all_series': all_series,
        'search_query': search_query,
        'total_drafts': drafts_qs.count(),
        'total_published': published_qs.count()
    })


@admin_required
@login_required
def manage_series(request):
    """Create and organize test series, sections, and subsections."""
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_series':
            name = request.POST.get('series_name', '').strip()
            description = request.POST.get('series_description', '').strip()
            exam_cover = request.FILES.get('exam_cover')

            if not name:
                messages.error(request, "Series name is required.")
                return redirect('builder_manage_series')

            base_slug = slugify(name)
            slug = base_slug
            counter = 1
            while TestSeries.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            if TestSeries.objects.filter(name__iexact=name).exists():
                messages.error(request, f"A series named '{name}' already exists.")
                return redirect('builder_manage_series')

            series = TestSeries.objects.create(
                name=name,
                slug=slug,
                description=description,
                exam_cover=exam_cover,
                is_active=True,
            )

            SeriesSection.objects.get_or_create(
                series=series,
                name="All Tests",
                defaults={
                    "slug": slugify("all-tests"),
                    "order": 1,
                    "is_active": True,
                },
            )

            exam_sections = _extract_exam_sections(request)
            for order, section in enumerate(exam_sections, start=1):
                TestSeriesExamSection.objects.create(
                    series=series,
                    title=section["title"],
                    body=section["body"],
                    image=section["image"],
                    order=order,
                )

            highlights = _extract_highlights(request)
            for order, highlight in enumerate(highlights, start=1):
                TestSeriesHighlight.objects.create(
                    series=series,
                    title=highlight["title"],
                    value=highlight["value"],
                    order=order,
                )

            messages.success(request, f"Series '{name}' created with default 'All Tests' section.")
            return redirect('builder_manage_series')

        if action == 'update_series_details':
            series_id = request.POST.get('series_id')
            series = get_object_or_404(TestSeries, id=series_id)
            exam_cover = request.FILES.get('exam_cover')

            if exam_cover:
                series.exam_cover = exam_cover
                series.save(update_fields=["exam_cover", "updated_at"])

            exam_sections = _extract_exam_sections(request)
            keep_ids = []

            for order, section in enumerate(exam_sections, start=1):
                section_id = section["id"]
                if section_id:
                    existing = TestSeriesExamSection.objects.filter(
                        id=section_id, series=series
                    ).first()
                else:
                    existing = None

                if existing:
                    existing.title = section["title"]
                    existing.body = section["body"]
                    existing.order = order
                    if section["image"]:
                        existing.image = section["image"]
                    existing.save()
                    keep_ids.append(existing.id)
                else:
                    created = TestSeriesExamSection.objects.create(
                        series=series,
                        title=section["title"],
                        body=section["body"],
                        image=section["image"],
                        order=order,
                    )
                    keep_ids.append(created.id)

            TestSeriesExamSection.objects.filter(series=series).exclude(id__in=keep_ids).delete()

            highlights = _extract_highlights(request)
            highlight_keep_ids = []

            for order, highlight in enumerate(highlights, start=1):
                highlight_id = highlight["id"]
                if highlight_id:
                    existing = TestSeriesHighlight.objects.filter(
                        id=highlight_id, series=series
                    ).first()
                else:
                    existing = None

                if existing:
                    existing.title = highlight["title"]
                    existing.value = highlight["value"]
                    existing.order = order
                    existing.save()
                    highlight_keep_ids.append(existing.id)
                else:
                    created = TestSeriesHighlight.objects.create(
                        series=series,
                        title=highlight["title"],
                        value=highlight["value"],
                        order=order,
                    )
                    highlight_keep_ids.append(created.id)

            TestSeriesHighlight.objects.filter(series=series).exclude(id__in=highlight_keep_ids).delete()

            messages.success(request, f"Exam details updated for '{series.name}'.")
            return redirect('builder_manage_series')

        if action == 'create_section':
            series_id = request.POST.get('section_series')
            section_name = request.POST.get('section_name', '').strip()

            if not series_id or not section_name:
                messages.error(request, "Series and section name are required.")
                return redirect('builder_manage_series')

            series = get_object_or_404(TestSeries, id=series_id)
            if SeriesSection.objects.filter(series=series, name__iexact=section_name).exists():
                messages.error(request, f"Section '{section_name}' already exists in {series.name}.")
                return redirect('builder_manage_series')

            base_slug = slugify(section_name)
            slug = base_slug
            counter = 1
            while SeriesSection.objects.filter(series=series, slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            SeriesSection.objects.create(
                series=series,
                name=section_name,
                slug=slug,
                order=SeriesSection.objects.filter(series=series).count() + 1,
                is_active=True,
            )

            messages.success(request, f"Section '{section_name}' added to {series.name}.")
            return redirect('builder_manage_series')

        if action == 'create_subsection':
            section_id = request.POST.get('subsection_section')
            subsection_name = request.POST.get('subsection_name', '').strip()

            if not section_id or not subsection_name:
                messages.error(request, "Section and subsection name are required.")
                return redirect('builder_manage_series')

            section = get_object_or_404(SeriesSection, id=section_id)
            if SeriesSubsection.objects.filter(section=section, name__iexact=subsection_name).exists():
                messages.error(request, f"Subsection '{subsection_name}' already exists in {section.name}.")
                return redirect('builder_manage_series')

            base_slug = slugify(subsection_name)
            slug = base_slug
            counter = 1
            while SeriesSubsection.objects.filter(section=section, slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            SeriesSubsection.objects.create(
                section=section,
                name=subsection_name,
                slug=slug,
                order=SeriesSubsection.objects.filter(section=section).count() + 1,
                is_active=True,
            )

            messages.success(request, f"Subsection '{subsection_name}' added under {section.name}.")
            return redirect('builder_manage_series')

    series_list = (
        TestSeries.objects.filter(is_active=True)
        .prefetch_related('sections__subsections', 'exam_sections', 'highlights')
        .order_by('name')
    )
    sections_list = SeriesSection.objects.filter(is_active=True).select_related('series')

    return render(request, 'test_builder/manage_series.html', {
        'series_list': series_list,
        'sections_list': sections_list,
    })


@admin_required
@login_required
def create_test(request):
    """Create new test draft"""
    if request.method == 'POST':
        series_id = request.POST.get('series')
        series_section_id = request.POST.get('series_section')
        series_subsection_id = request.POST.get('series_subsection')
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        duration_minutes = request.POST.get('duration_minutes')
        marks_per_question = request.POST.get('marks_per_question')
        negative_marks = request.POST.get('negative_marks')
        use_sectional_timing = request.POST.get('use_sectional_timing') == 'true'
        num_sections = int(request.POST.get('num_sections', 1))
        
        series = get_object_or_404(TestSeries, id=series_id)

        # Resolve series section/subsection (default to "All Tests")
        series_section = None
        if series_section_id:
            series_section = SeriesSection.objects.filter(
                id=series_section_id, series=series
            ).first()

        if not series_section:
            series_section, _ = SeriesSection.objects.get_or_create(
                series=series,
                name="All Tests",
                defaults={
                    "slug": slugify("all-tests"),
                    "order": 1,
                    "is_active": True,
                },
            )

        series_subsection = None
        if series_subsection_id and series_section:
            series_subsection = SeriesSubsection.objects.filter(
                id=series_subsection_id, section=series_section
            ).first()
        
        # Check for duplicate test name in this series (from ANY admin, not just current user)
        # This prevents two admins from creating tests with the same name
        existing_draft = TestDraft.objects.filter(series=series, name__iexact=name).first()
        existing_published = Test.objects.filter(series=series, name__iexact=name, is_active=True).first()
        
        if existing_draft or existing_published:
            messages.error(request, f"❌ A test named '{name}' already exists in {series.name}. "
                                   f"Another admin might be creating it right now. Please choose a different name or wait.")
            series_list = TestSeries.objects.filter(is_active=True)
            series_sections = SeriesSection.objects.filter(is_active=True).select_related('series')
            series_subsections = SeriesSubsection.objects.filter(is_active=True).select_related('section', 'section__series')
            return render(request, 'test_builder/create_test.html', {
                'series_list': series_list,
                'series_sections': series_sections,
                'series_subsections': series_subsections,
                'form_data': {
                    'name': name,
                    'description': description,
                    'duration_minutes': duration_minutes,
                    'marks_per_question': marks_per_question,
                    'negative_marks': negative_marks,
                    'num_sections': num_sections,
                    'use_sectional_timing': use_sectional_timing,
                    'selected_series': series_id,
                    'selected_series_section': series_section_id,
                    'selected_series_subsection': series_subsection_id,
                }
            })
        
        # Create draft
        draft = TestDraft.objects.create(
            series=series,
            series_section=series_section,
            series_subsection=series_subsection,
            name=name,
            description=description,
            duration_minutes=duration_minutes,
            marks_per_question=marks_per_question,
            negative_marks=negative_marks,
            use_sectional_timing=use_sectional_timing,
            created_by=request.user
        )
        
        # Create empty sections
        for i in range(1, num_sections + 1):
            SectionDraft.objects.create(
                test_draft=draft,
                name=f"Section {i}",
                order=i
            )
        
        messages.success(request, f"Test '{name}' created! Now add sections and questions.")
        return redirect('manage_sections', draft_id=draft.id)
    
    series_list = TestSeries.objects.filter(is_active=True)
    series_sections = SeriesSection.objects.filter(is_active=True).select_related('series')
    series_subsections = SeriesSubsection.objects.filter(is_active=True).select_related('section', 'section__series')
    return render(request, 'test_builder/create_test.html', {
        'series_list': series_list,
        'series_sections': series_sections,
        'series_subsections': series_subsections,
    })


@admin_required
@login_required
def manage_sections(request, draft_id):
    """Manage sections and add questions"""
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    
    # Check if draft is locked by another admin
    if not draft.can_edit(request.user):
        messages.error(
            request, 
            f"❌ This test is currently being edited by {draft.locked_by.username}. "
            f"Please wait until they finish. Lock will auto-expire after 30 minutes of inactivity."
        )
        return redirect('builder_dashboard')
    
    # Acquire lock for this admin
    draft.acquire_lock(request.user)
    
    sections = draft.sections.all()
    
    if request.method == 'POST':
        # Refresh lock timestamp
        draft.refresh_lock(request.user)

        action = request.POST.get('action', 'update_sections')

        if action == 'update_test_metadata':
            new_name = request.POST.get('test_name', '').strip()
            new_duration = request.POST.get('duration_minutes', '').strip()
            new_marks = request.POST.get('marks_per_question', '').strip()
            new_negative = request.POST.get('negative_marks', '').strip()

            errors = []
            if not new_name:
                errors.append("Test name cannot be empty.")
            if not new_duration or not new_duration.isdigit() or int(new_duration) < 1:
                errors.append("Duration must be a positive integer.")
            try:
                float(new_marks)
            except (ValueError, TypeError):
                errors.append("Marks per question must be a valid number.")
            try:
                float(new_negative)
            except (ValueError, TypeError):
                errors.append("Negative marks must be a valid number.")

            if errors:
                for e in errors:
                    messages.error(request, e)
            else:
                # Check name uniqueness (excluding self)
                if (
                    TestDraft.objects.filter(series=draft.series, name__iexact=new_name)
                    .exclude(id=draft.id)
                    .exists()
                ):
                    messages.error(request, f"A test named '{new_name}' already exists in {draft.series.name}.")
                else:
                    from decimal import Decimal
                    draft.name = new_name
                    draft.duration_minutes = int(new_duration)
                    draft.marks_per_question = Decimal(new_marks)
                    draft.negative_marks = Decimal(new_negative)
                    draft.save(update_fields=['name', 'duration_minutes', 'marks_per_question', 'negative_marks'])
                    messages.success(request, "Test details updated successfully!")

            return redirect('manage_sections', draft_id=draft.id)

        # Update section names
        for section in sections:
            section_name = request.POST.get(f'section_{section.id}_name')
            if section_name:
                section.name = section_name
            
            # Update section time limit if sectional timing is enabled
            if draft.use_sectional_timing:
                section_time = request.POST.get(f'section_{section.id}_time')
                if section_time:
                    try:
                        section.time_limit_minutes = int(section_time)
                    except (ValueError, TypeError):
                        pass
            
            section.save()
        
        messages.success(request, "Sections updated!")
        return redirect('manage_sections', draft_id=draft.id)
    
    return render(request, 'test_builder/manage_sections.html', {
        'draft': draft,
        'sections': sections
    })


@admin_required
@login_required
def manage_questions(request, draft_id, section_id):
    """Add/edit questions and options"""
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    
    # Check if draft is locked by another admin
    if not draft.can_edit(request.user):
        messages.error(
            request, 
            f"❌ This test is currently being edited by {draft.locked_by.username}. "
            f"Please wait until they finish."
        )
        return redirect('builder_dashboard')
    
    # Refresh lock timestamp
    draft.refresh_lock(request.user)
    
    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)
    questions = section.questions.all()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_question':
            # Add new question
            question_text = request.POST.get('question_text', '').strip()
            solution_text = request.POST.get('solution_text', '')
            question_image = request.FILES.get('question_image')
            solution_image = request.FILES.get('solution_image')
            
            # Validation: Question must have at least text or image
            if not question_text and not question_image:
                messages.error(request, "❌ Question must have either text or an image (or both).")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            # Collect and validate options
            options_data = []
            for i in range(1, 5):
                option_text = request.POST.get(f'option_{i}_text', '').strip()
                option_image = request.FILES.get(f'option_{i}_image')
                is_correct = request.POST.get(f'option_{i}_correct') == 'on'
                
                # If option has text or image, add it
                if option_text or option_image:
                    options_data.append({
                        'text': option_text,
                        'image': option_image,
                        'is_correct': is_correct,
                        'order': i
                    })
                # If neither text nor image, skip this option
            
            # Validation: At least one option must be provided
            if len(options_data) == 0:
                messages.error(request, "❌ Question must have at least one option.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            # Validation: Exactly one correct answer must be selected
            correct_count = sum(1 for opt in options_data if opt['is_correct'])
            if correct_count == 0:
                messages.error(request, "❌ Please select exactly one correct answer. No correct answer is currently selected.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            elif correct_count > 1:
                messages.error(request, f"❌ Please select exactly one correct answer. You have selected {correct_count} correct answers.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            order = section.questions.count() + 1
            question = QuestionDraft.objects.create(
                section=section,
                question_text=question_text,
                question_image=question_image,
                solution_text=solution_text,
                solution_image=solution_image,
                order=order
            )
            
            # Add options
            for option_data in options_data:
                OptionDraft.objects.create(
                    question=question,
                    option_text=option_data['text'],
                    option_image=option_data['image'],
                    is_correct=option_data['is_correct'],
                    order=option_data['order']
                )
            
            messages.success(request, "✅ Question added successfully!")
            return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
        
        elif action == 'edit_question':
            # Edit existing question
            question_id = request.POST.get('question_id')
            question = get_object_or_404(QuestionDraft, id=question_id, section=section)
            
            question_text = request.POST.get('question_text', '').strip()
            question.question_text = question_text
            question.solution_text = request.POST.get('solution_text', '')
            
            if request.FILES.get('question_image'):
                question.question_image = request.FILES.get('question_image')
            if request.FILES.get('solution_image'):
                question.solution_image = request.FILES.get('solution_image')
            
            # Validation: Question must have at least text or image
            if not question.question_text and not question.question_image:
                messages.error(request, "❌ Question must have either text or an image (or both).")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            question.save()
            
            # Collect and validate options
            options_data = []
            for i in range(1, 5):
                option_text = request.POST.get(f'option_{i}_text', '').strip()
                option_image = request.FILES.get(f'option_{i}_image')
                is_correct = request.POST.get(f'option_{i}_correct') == 'on'
                
                # If option has text or image, add it
                if option_text or option_image:
                    options_data.append({
                        'text': option_text,
                        'image': option_image,
                        'is_correct': is_correct,
                        'order': i
                    })
            
            # Validation: At least one option must be provided
            if len(options_data) == 0:
                messages.error(request, "❌ Question must have at least one option.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            # Validation: Exactly one correct answer must be selected
            correct_count = sum(1 for opt in options_data if opt['is_correct'])
            if correct_count == 0:
                messages.error(request, "❌ Please select exactly one correct answer. No correct answer is currently selected.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            elif correct_count > 1:
                messages.error(request, f"❌ Please select exactly one correct answer. You have selected {correct_count} correct answers.")
                return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
            
            # Update options
            question.options.all().delete()
            for option_data in options_data:
                OptionDraft.objects.create(
                    question=question,
                    option_text=option_data['text'],
                    option_image=option_data['image'],
                    is_correct=option_data['is_correct'],
                    order=option_data['order']
                )
            
            messages.success(request, "✅ Question updated successfully!")
            return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
        
        elif action == 'delete_question':
            question_id = request.POST.get('question_id')
            QuestionDraft.objects.filter(id=question_id).delete()
            messages.success(request, "Question deleted!")
            return redirect('manage_questions', draft_id=draft.id, section_id=section.id)
    
    return render(request, 'test_builder/manage_questions.html', {
        'draft': draft,
        'section': section,
        'questions': questions
    })


@admin_required
@login_required
def publish_test(request, draft_id):
    """Convert draft to actual test or update existing published test"""
    from django.db import IntegrityError

    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    # Check if locked by another admin
    if not draft.can_edit(request.user):
        messages.error(request, f"❌ This test is currently being edited by {draft.locked_by.username}. "
                                f"Please wait until they finish. Lock will auto-expire after 30 minutes of inactivity.")
        return redirect('builder_dashboard')

    if draft.is_published:
        messages.warning(request, "This test is already published!")
        return redirect('builder_dashboard')

    # ── Phase 1: Pre-publish validation (no DB writes) ──────────────────
    # All validation runs before touching the database so that:
    # (a) partial-write corruption inside the atomic block cannot occur, and
    # (b) admins are always redirected back to the live editor with a clear message.
    section_names_seen = {}
    for section_draft in draft.sections.all():
        name = section_draft.name.strip()
        if not name:
            messages.error(request, "❌ A section has an empty name. Please name all sections before publishing.")
            return redirect('live_editor', draft_id=draft_id)
        if name in section_names_seen:
            messages.error(request, f"❌ Two sections share the name '{name}'. Each section must have a unique name.")
            return redirect('live_editor', draft_id=draft_id)
        section_names_seen[name] = True

        for question_draft in section_draft.questions.all():
            if not question_draft.question_text and not question_draft.question_image:
                messages.error(request, f"❌ Cannot publish: A question in '{name}' has no text or image.")
                return redirect('live_editor', draft_id=draft_id)

            options = list(question_draft.options.all())
            if not options:
                messages.error(request, f"❌ Cannot publish: A question in '{name}' has no options.")
                return redirect('live_editor', draft_id=draft_id)

            correct = sum(1 for o in options if o.is_correct)
            if correct == 0:
                messages.error(request, f"❌ Cannot publish: A question in '{name}' has no correct answer marked.")
                return redirect('live_editor', draft_id=draft_id)
            if correct > 1:
                messages.error(request, f"❌ Cannot publish: A question in '{name}' has {correct} correct answers. Only 1 is allowed.")
                return redirect('live_editor', draft_id=draft_id)

            for opt in options:
                if not opt.option_text and not opt.option_image:
                    messages.error(request, f"❌ Cannot publish: An option in '{name}' has no text or image.")
                    return redirect('live_editor', draft_id=draft_id)

    # ── Phase 2: DB writes (all validation passed above) ────────────────
    # NOTE: transaction.atomic() is used as a context manager (not a decorator) so
    # that catching a DatabaseError in the except clauses below does NOT operate on
    # a poisoned transaction.  With the old @transaction.atomic decorator the entire
    # function — including the messages/session writes in except — ran inside one
    # transaction; any DB error caught inside would mark the transaction as needing
    # rollback and the subsequent session write for messages.error() would raise
    # TransactionManagementError → 500.
    try:
        with transaction.atomic():
            series_section = draft.series_section
            if not series_section:
                series_section, _ = SeriesSection.objects.get_or_create(
                    series=draft.series,
                    name="All Tests",
                    defaults={
                        "slug": slugify("all-tests"),
                        "order": 1,
                        "is_active": True,
                    },
                )

            series_subsection = draft.series_subsection
            if series_subsection and series_subsection.section != series_section:
                series_subsection = None

            # Check if this draft has a published test from before (republishing case)
            published_test = None
            if draft.published_test_id:
                try:
                    published_test = Test.objects.get(id=draft.published_test_id)
                    # Delete old sections (this will cascade delete questions and options)
                    published_test.sections.all().delete()
                except Test.DoesNotExist:
                    published_test = None

            if published_test:
                # Republishing: Update existing test
                published_test.name = draft.name
                published_test.description = draft.description
                published_test.series_section = series_section
                published_test.series_subsection = series_subsection
                published_test.duration_seconds = draft.duration_minutes * 60
                published_test.marks_per_question = draft.marks_per_question
                published_test.negative_marks_per_question = draft.negative_marks
                published_test.use_sectional_timing = draft.use_sectional_timing
                published_test.shuffle_questions = draft.shuffle_questions
                published_test.is_active = True
                published_test.save()
                test = published_test
            else:
                # First time publishing: Create new test
                # Use a unique slug to avoid conflicts with old deactivated tests
                base_slug = slugify(draft.name)
                slug = base_slug
                counter = 1

                while Test.objects.filter(series=draft.series, slug=slug).exists():
                    slug = f"{base_slug}-v{counter}"
                    counter += 1

                test = Test.objects.create(
                    series=draft.series,
                    series_section=series_section,
                    series_subsection=series_subsection,
                    name=draft.name,
                    slug=slug,
                    description=draft.description,
                    duration_seconds=draft.duration_minutes * 60,
                    marks_per_question=draft.marks_per_question,
                    negative_marks_per_question=draft.negative_marks,
                    use_sectional_timing=draft.use_sectional_timing,
                    shuffle_questions=draft.shuffle_questions,
                    is_active=True
                )

            # Create sections — use sequential index (1, 2, 3…) instead of draft.order to
            # guarantee uniqueness against uq_section_order_within_test even if draft orders drifted.
            for seq_order, section_draft in enumerate(draft.sections.all(), start=1):
                section_time_seconds = 0
                if draft.use_sectional_timing and section_draft.time_limit_minutes:
                    section_time_seconds = section_draft.time_limit_minutes * 60

                section = Section.objects.create(
                    test=test,
                    name=section_draft.name,
                    order=seq_order,
                    time_limit_seconds=section_time_seconds
                )

                for question_draft in section_draft.questions.all():
                    question = Question.objects.create(
                        section=section,
                        text=question_draft.question_text,
                        image=question_draft.question_image,
                        explanation=question_draft.solution_text,
                        solution_image=question_draft.solution_image
                    )

                    for option_draft in question_draft.options.all():
                        Option.objects.create(
                            question=question,
                            text=option_draft.option_text,
                            image=option_draft.option_image,
                            is_correct=option_draft.is_correct,
                            order=option_draft.order
                        )

            # Mark draft as published and store the published test ID
            draft.is_published = True
            draft.published_test_id = test.id
            draft.release_lock()  # Release lock after successful publish
            draft.save()

        # transaction committed — safe to read test/published_test outside the block
        action_type = "updated" if published_test else "published"
        messages.success(request, f"Test '{test.name}' {action_type} successfully! Students can now take this test.")
        return redirect('builder_dashboard')

    except IntegrityError as e:
        logger.exception("IntegrityError in publish_test for draft_id=%s user=%s", draft_id, request.user)
        messages.error(request, f"❌ Database conflict during publish — likely a duplicate section name or ordering issue. Details: {e}")
        return redirect('live_editor', draft_id=draft_id)
    except Exception as e:
        logger.exception("Unexpected error in publish_test for draft_id=%s user=%s", draft_id, request.user)
        messages.error(request, f"❌ An unexpected error occurred while publishing: {e}")
        return redirect('live_editor', draft_id=draft_id)


@admin_required
@login_required
def delete_draft(request, draft_id):
    """Delete a draft"""
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    
    # Check if locked by another admin (in case they're deleting while someone is editing)
    if not draft.can_edit(request.user):
        messages.error(request, f"❌ This test is currently being edited by {draft.locked_by.username}. "
                                f"Cannot delete while being edited.")
        return redirect('builder_dashboard')
    
    if request.method == 'POST':
        draft.release_lock()  # Release lock before deletion
        draft.delete()
        messages.success(request, "Draft deleted successfully!")
        return redirect('builder_dashboard')
    
    return render(request, 'test_builder/confirm_delete.html', {'draft': draft})


@admin_required
@login_required
@transaction.atomic
def unpublish_test(request, draft_id):
    """Unpublish a test to make it editable again"""
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user, is_published=True)
    
    # Check if locked by another admin
    if not draft.can_edit(request.user):
        messages.error(request, f"❌ This test is currently being accessed by {draft.locked_by.username}. "
                                f"Please wait until they finish. Lock will auto-expire after 30 minutes of inactivity.")
        return redirect('builder_dashboard')
    
    if request.method == 'POST':
        # Get the published test
        if hasattr(draft, 'published_test_id') and draft.published_test_id:
            try:
                published_test = Test.objects.get(id=draft.published_test_id)
                
                # Deactivate the published test
                published_test.is_active = False
                published_test.save()
                
                messages.info(request, f"Test '{published_test.name}' has been deactivated and is no longer available to students.")
            except Test.DoesNotExist:
                pass
        
        # Mark draft as unpublished so it can be edited
        draft.is_published = False
        draft.release_lock()  # Release lock after unpublishing
        draft.save()
        
        messages.success(request, f"Test '{draft.name}' is now editable. Make your changes and publish again.")
        return redirect('live_editor', draft_id=draft.id)
    
    return render(request, 'test_builder/confirm_unpublish.html', {'draft': draft})


@admin_required
@login_required
@transaction.atomic
def delete_published_test(request, draft_id):
    """Delete a published test and its draft"""
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user, is_published=True)
    
    # Check if locked by another admin
    if not draft.can_edit(request.user):
        messages.error(request, f"❌ This test is currently being accessed by {draft.locked_by.username}. "
                                f"Cannot delete while being accessed.")
        return redirect('builder_dashboard')
    
    if request.method == 'POST':
        # Delete the published test if it exists
        if hasattr(draft, 'published_test_id') and draft.published_test_id:
            try:
                published_test = Test.objects.get(id=draft.published_test_id)
                test_name = published_test.name
                published_test.delete()
                messages.success(request, f"Published test '{test_name}' deleted successfully!")
            except Test.DoesNotExist:
                pass
        
        # Delete the draft
        draft.release_lock()  # Release lock before deletion
        draft.delete()
        
        return redirect('builder_dashboard')
    
    return render(request, 'test_builder/confirm_delete_published.html', {'draft': draft})


@admin_required
@login_required
def search_suggestions(request):
    """AJAX endpoint for search suggestions"""
    from django.http import JsonResponse

@admin_required
@login_required
@require_http_methods(["POST"])
def deactivate_orphaned_test(request, test_id):
    """Deactivate an active Test that has no linked published draft (orphaned)."""
    from django.http import JsonResponse
    test = get_object_or_404(Test, id=test_id, is_active=True)
    # Verify it is truly orphaned (no draft from this user tracks it)
    if TestDraft.objects.filter(created_by=request.user, published_test_id=test_id).exists():
        return JsonResponse({'success': False, 'message': 'This test is managed by a draft; use Edit Test instead.'}, status=400)
    test.is_active = False
    test.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'message': f"Test '{test.name}' has been hidden from students."})


    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'suggestions': []})
    
    # Search in test names and series names
    test_names = TestDraft.objects.filter(
        created_by=request.user,
        name__icontains=query
    ).values_list('name', flat=True).distinct()[:5]
    
    series_names = TestSeries.objects.filter(
        drafts__created_by=request.user,
        name__icontains=query
    ).values_list('name', flat=True).distinct()[:5]
    
    suggestions = []
    
    # Add test names
    for name in test_names:
        suggestions.append({
            'text': name,
            'type': 'test'
        })
    
    # Add series names
    for name in series_names:
        suggestions.append({
            'text': name,
            'type': 'series'
        })
    
    return JsonResponse({'suggestions': suggestions[:8]})


@admin_required
@login_required
@require_http_methods(["POST"])
def toggle_test_active(request, draft_id):
    """Toggle test between active/inactive (publish/unpublish) without editing"""
    from django.http import JsonResponse
    from django.views.decorators.csrf import csrf_protect
    
    draft = get_object_or_404(TestDraft, id=draft_id, is_published=True)
    
    # Verify it's actually published
    if not hasattr(draft, 'published_test_id') or not draft.published_test_id:
        return JsonResponse({'success': False, 'message': 'Test is not published'}, status=400)
    
    try:
        published_test = Test.objects.get(id=draft.published_test_id)
    except Test.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Published test not found'}, status=400)
    
    # Toggle the is_active status
    published_test.is_active = not published_test.is_active
    published_test.save()
    
    action = "published" if published_test.is_active else "unpublished"
    status_text = "Live ✓" if published_test.is_active else "Hidden 🔒"
    
    return JsonResponse({
        'success': True,
        'is_active': published_test.is_active,
        'status_text': status_text,
        'message': f"Test '{published_test.name}' has been {action}."
    })


# ──────────────────────────────────────────────
# LIVE EDITOR — immersive question editor
# ──────────────────────────────────────────────

@admin_required
@login_required
def live_editor(request, draft_id):
    """Full-screen live editor: mirrors student test UI with editing controls."""
    import json
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    if not draft.can_edit(request.user):
        messages.error(
            request,
            f"❌ This test is currently being edited by {draft.locked_by.username}. "
            f"Lock auto-expires after 30 minutes of inactivity."
        )
        return redirect('builder_dashboard')

    draft.acquire_lock(request.user)

    # Heal any corrupted section orders (gaps or duplicates from past deletes)
    # so the editor always works with clean sequential 1, 2, 3... ordering.
    for i, sec in enumerate(draft.sections.order_by('order', 'id'), start=1):
        if sec.order != i:
            sec.order = i
            sec.save(update_fields=['order'])

    sections_data = []
    for section in draft.sections.all():
        questions_data = []
        for question in section.questions.all():
            options_data = [
                {
                    'id': opt.id,
                    'text': opt.option_text,
                    'image_url': opt.option_image.url if opt.option_image else None,
                    'is_correct': opt.is_correct,
                    'order': opt.order,
                }
                for opt in question.options.all()
            ]
            questions_data.append({
                'id': question.id,
                'order': question.order,
                'question_text': question.question_text,
                'image_url': question.question_image.url if question.question_image else None,
                'solution_text': question.solution_text,
                'solution_image_url': question.solution_image.url if question.solution_image else None,
                'options': options_data,
            })
        sections_data.append({
            'id': section.id,
            'name': section.name,
            'order': section.order,
            'questions': questions_data,
        })

    return render(request, 'test_builder/live_editor.html', {
        'draft': draft,
        'sections_for_import': draft.sections.all(),
        'sections_json': json.dumps(sections_data),
    })


@admin_required
@login_required
@require_http_methods(["POST"])
def api_add_section(request, draft_id):
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    draft.refresh_lock(request.user)
    name = request.POST.get('name', '').strip() or 'New Section'
    order = draft.sections.count() + 1
    section = SectionDraft.objects.create(test_draft=draft, name=name, order=order)
    return JsonResponse({'success': True, 'section': {'id': section.id, 'name': section.name, 'order': section.order}})


@admin_required
@login_required
@require_http_methods(["POST"])
def api_rename_section(request, draft_id, section_id):
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)
    draft.refresh_lock(request.user)
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Name cannot be empty.'}, status=400)
    section.name = name
    section.save()
    return JsonResponse({'success': True, 'name': section.name})


@admin_required
@login_required
@require_http_methods(["POST"])
def api_delete_section(request, draft_id, section_id):
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)
    draft.refresh_lock(request.user)
    if draft.sections.count() <= 1:
        return JsonResponse({'success': False, 'error': 'Cannot delete the only section.'}, status=400)
    section.delete()
    # Renumber remaining sections 1, 2, 3… so order values never have gaps or duplicates.
    # This prevents uq_section_order_within_test IntegrityError on publish.
    for i, sec in enumerate(SectionDraft.objects.filter(test_draft=draft).order_by('order', 'id'), start=1):
        if sec.order != i:
            sec.order = i
            sec.save(update_fields=['order'])
    return JsonResponse({'success': True})


@admin_required
@login_required
@require_http_methods(["POST"])
def api_save_question(request, draft_id):
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    draft.refresh_lock(request.user)

    section_id = request.POST.get('section_id')
    question_id = request.POST.get('question_id', '').strip() or None
    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)

    question_text = request.POST.get('question_text', '').strip()
    solution_text = request.POST.get('solution_text', '').strip()
    question_image = request.FILES.get('question_image')
    solution_image = request.FILES.get('solution_image')
    clear_question_image = request.POST.get('clear_question_image') == '1'
    clear_solution_image = request.POST.get('clear_solution_image') == '1'

    # Collect options from request
    option_count = int(request.POST.get('option_count', 0))
    options_data = []
    for i in range(option_count):
        opt_id = request.POST.get(f'option_{i}_id', '').strip() or None
        opt_text = request.POST.get(f'option_{i}_text', '').strip()
        opt_image = request.FILES.get(f'option_{i}_image')
        is_correct = request.POST.get(f'option_{i}_correct') == '1'
        options_data.append({'id': opt_id, 'text': opt_text, 'image': opt_image, 'is_correct': is_correct, 'order': i + 1})

    # Validate question content
    if not question_text and not question_image:
        if question_id:
            existing_q = QuestionDraft.objects.filter(id=question_id, section=section).first()
            if not existing_q or (not existing_q.question_image):
                return JsonResponse({'success': False, 'error': 'Question must have text or an image.'}, status=400)
        else:
            return JsonResponse({'success': False, 'error': 'Question must have text or an image.'}, status=400)

    if len(options_data) == 0:
        return JsonResponse({'success': False, 'error': 'At least one option is required.'}, status=400)

    correct_count = sum(1 for o in options_data if o['is_correct'])
    if correct_count == 0:
        return JsonResponse({'success': False, 'error': 'Please mark one option as the correct answer.'}, status=400)
    if correct_count > 1:
        return JsonResponse({'success': False, 'error': f'Only one correct answer allowed ({correct_count} selected).'}, status=400)

    # Save / update question
    if question_id:
        question = get_object_or_404(QuestionDraft, id=question_id, section=section)
        question.question_text = question_text
        question.solution_text = solution_text
        if question_image:
            question.question_image = question_image
        elif clear_question_image:
            question.question_image = None
        if solution_image:
            question.solution_image = solution_image
        elif clear_solution_image:
            question.solution_image = None
        question.save()
    else:
        order = section.questions.count() + 1
        question = QuestionDraft.objects.create(
            section=section,
            question_text=question_text,
            question_image=question_image,
            solution_text=solution_text,
            solution_image=solution_image,
            order=order,
        )

    # Update options: update existing, create new, delete removed
    submitted_ids = set()
    for opt_data in options_data:
        if opt_data['id']:
            existing_opt = OptionDraft.objects.filter(id=opt_data['id'], question=question).first()
            if existing_opt:
                existing_opt.option_text = opt_data['text']
                existing_opt.is_correct = opt_data['is_correct']
                existing_opt.order = opt_data['order']
                if opt_data['image']:
                    existing_opt.option_image = opt_data['image']
                existing_opt.save()
                submitted_ids.add(existing_opt.id)
                continue
        new_opt = OptionDraft.objects.create(
            question=question,
            option_text=opt_data['text'],
            option_image=opt_data['image'],
            is_correct=opt_data['is_correct'],
            order=opt_data['order'],
        )
        submitted_ids.add(new_opt.id)

    # Remove options no longer present
    question.options.exclude(id__in=submitted_ids).delete()

    options_resp = [
        {
            'id': opt.id,
            'text': opt.option_text,
            'image_url': opt.option_image.url if opt.option_image else None,
            'is_correct': opt.is_correct,
            'order': opt.order,
        }
        for opt in question.options.all()
    ]
    return JsonResponse({
        'success': True,
        'question': {
            'id': question.id,
            'order': question.order,
            'question_text': question.question_text,
            'image_url': question.question_image.url if question.question_image else None,
            'solution_text': question.solution_text,
            'solution_image_url': question.solution_image.url if question.solution_image else None,
            'options': options_resp,
        }
    })


@admin_required
@login_required
@require_http_methods(["POST"])
def api_delete_question(request, draft_id, question_id):
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    question = get_object_or_404(QuestionDraft, id=question_id, section__test_draft=draft)
    draft.refresh_lock(request.user)
    section_id = question.section_id
    question.delete()
    # Reorder remaining questions in sequence
    for i, q in enumerate(QuestionDraft.objects.filter(section_id=section_id).order_by('order'), start=1):
        if q.order != i:
            q.order = i
            q.save(update_fields=['order'])
    return JsonResponse({'success': True})


@admin_required
@login_required
@require_http_methods(["POST"])
def api_toggle_shuffle(request, draft_id):
    """Toggle shuffle_questions flag on a draft. Returns new state."""
    from django.http import JsonResponse
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    draft.refresh_lock(request.user)
    enabled = request.POST.get('enabled', '').lower() == 'true'
    draft.shuffle_questions = enabled
    draft.save(update_fields=['shuffle_questions'])
    return JsonResponse({'success': True, 'shuffle_questions': draft.shuffle_questions})


@admin_required
@login_required
def api_validate_draft(request, draft_id):
    """
    Validate a draft before publishing — returns JSON with all errors grouped by section/question.
    No DB writes are performed here. Used by the live editor's pre-publish check.
    """
    from django.http import JsonResponse

    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    global_errors = []
    sections_result = []
    is_valid = True

    # Detect duplicate section names (causes IntegrityError on uq_section_name_within_test)
    section_name_counts = {}
    for sec in draft.sections.all():
        n = sec.name.strip()
        section_name_counts[n] = section_name_counts.get(n, 0) + 1
    duplicate_names = {n for n, cnt in section_name_counts.items() if cnt > 1}
    if duplicate_names:
        is_valid = False
        for dup in sorted(duplicate_names):
            global_errors.append(f"Duplicate section name: '{dup}' — each section must have a unique name")

    # NOTE: Duplicate section orders are NOT checked here because publish_test always
    # normalises orders to sequential 1,2,3… via enumerate, so they never reach the DB.
    # Orders are also healed when the live editor is opened.

    for section_draft in draft.sections.all():
        section_error = None
        question_errors = []
        question_warnings = []
        name = section_draft.name.strip()

        if not name:
            section_error = "Section name cannot be empty"
            is_valid = False
        elif name in duplicate_names:
            section_error = "Duplicate section name — rename this to something unique"
            is_valid = False

        for q in section_draft.questions.all():
            q_error_parts = []
            q_warning_parts = []

            if not q.question_text and not q.question_image:
                q_error_parts.append("no question text or image")
                is_valid = False

            options = list(q.options.all())
            if not options:
                q_error_parts.append("no options added")
                is_valid = False
            else:
                correct_count = sum(1 for o in options if o.is_correct)
                if correct_count == 0:
                    q_error_parts.append("no correct answer marked")
                    is_valid = False
                elif correct_count > 1:
                    q_error_parts.append(f"{correct_count} correct answers (only 1 allowed)")
                    is_valid = False

                for opt in options:
                    if not opt.option_text and not opt.option_image:
                        q_error_parts.append("an option has no text or image")
                        is_valid = False
                        break

                # Soft warning: duplicate option text within the same question
                option_texts = [o.option_text.strip().lower() for o in options if o.option_text.strip()]
                if len(option_texts) != len(set(option_texts)):
                    q_warning_parts.append("two or more options have identical text")

            if q_error_parts:
                question_errors.append({
                    'id': q.id,
                    'order': q.order,
                    'error': '; '.join(q_error_parts),
                })
            if q_warning_parts:
                question_warnings.append({
                    'id': q.id,
                    'order': q.order,
                    'warning': '; '.join(q_warning_parts),
                })

        sections_result.append({
            'id': section_draft.id,
            'name': section_draft.name,
            'section_error': section_error,
            'question_errors': question_errors,
            'question_warnings': question_warnings,
        })

    return JsonResponse({
        'valid': is_valid,
        'global_errors': global_errors,
        'sections': sections_result,
    })


@admin_required
@login_required
@require_http_methods(["POST"])
def import_pdf_to_draft(request, draft_id):
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    if not draft.can_edit(request.user):
        messages.error(
            request,
            f"This test is currently being edited by {draft.locked_by.username}. Please wait until they finish.",
        )
        return redirect('builder_dashboard')

    draft.acquire_lock(request.user)

    section_id = request.POST.get('section_id', '').strip()
    pdf_file = request.FILES.get('pdf_file')
    auto_latex = request.POST.get('auto_latex') == '1'

    if not section_id:
        messages.error(request, 'Select a section before importing a PDF.')
        return redirect('live_editor', draft_id=draft.id)

    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)

    if not pdf_file:
        messages.error(request, 'Choose a PDF file to import.')
        return redirect('live_editor', draft_id=draft.id)

    filename = (pdf_file.name or '').lower()
    if not filename.endswith('.pdf'):
        messages.error(request, 'Only PDF files can be imported here.')
        return redirect('live_editor', draft_id=draft.id)

    import_job = PDFImportJob.objects.create(
        draft=draft,
        section=section,
        uploaded_by=request.user,
        source_filename=pdf_file.name or 'upload.pdf',
    )

    try:
        result = import_pdf_into_section(
            section,
            pdf_file,
            import_job=import_job,
            auto_latex=auto_latex,
        )
    except Exception as exc:
        messages.error(request, f'PDF import failed: {exc}')
        return redirect('live_editor', draft_id=draft.id)

    imported_count = result.get('imported_count', 0)
    skipped_count = result.get('skipped_count', 0)
    skip_summary = result.get('skip_summary', [])
    provider_name = result.get('provider_name', 'unknown')
    latex_converted_fields = result.get('latex_converted_fields', 0)

    if imported_count:
        messages.success(
            request,
            f"Imported {imported_count} question{'s' if imported_count != 1 else ''} into '{section.name}' using {provider_name} extraction.",
        )
    else:
        messages.warning(
            request,
            'No questions were imported because the parser could not find any high-confidence single-correct MCQs.',
        )

    if skipped_count:
        summary = ', '.join(skip_summary[:4])
        if len(skip_summary) > 4:
            summary += ', ...'
        messages.warning(
            request,
            f"Skipped {skipped_count} question{'s' if skipped_count != 1 else ''} to preserve accuracy"
            + (f': {summary}.' if summary else '.'),
        )

    if auto_latex and latex_converted_fields:
        messages.info(
            request,
            f'Applied LaTeX conversion to {latex_converted_fields} imported field'
            f"{'s' if latex_converted_fields != 1 else ''} for better math formatting.",
        )

    return redirect('live_editor', draft_id=draft.id)


@admin_required
@login_required
@require_http_methods(["POST"])
def import_json_to_draft(request, draft_id):
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    if not draft.can_edit(request.user):
        messages.error(
            request,
            f"This test is currently being edited by {draft.locked_by.username}. Please wait until they finish.",
        )
        return redirect('builder_dashboard')

    draft.acquire_lock(request.user)

    section_id = request.POST.get('section_id', '').strip()
    json_text = request.POST.get('json_text', '').strip()

    if not section_id:
        messages.error(request, 'Select a section before importing.')
        return redirect('live_editor', draft_id=draft.id)

    section = get_object_or_404(SectionDraft, id=section_id, test_draft=draft)

    if not json_text:
        messages.error(request, 'Paste the JSON content before importing.')
        return redirect('live_editor', draft_id=draft.id)

    try:
        result = import_json_into_section(section, json_text)
    except ValueError as exc:
        messages.error(request, f'JSON import failed: {exc}')
        return redirect('live_editor', draft_id=draft.id)
    except Exception as exc:
        messages.error(request, f'JSON import failed unexpectedly: {exc}')
        return redirect('live_editor', draft_id=draft.id)

    imported_count = result.get('imported_count', 0)
    skipped_count = result.get('skipped_count', 0)
    skip_summary = result.get('skip_summary', [])

    if imported_count:
        messages.success(
            request,
            f"Imported {imported_count} question{'s' if imported_count != 1 else ''} into '{section.name}'.",
        )
    else:
        messages.warning(request, 'No questions were imported. Check the JSON format.')

    if skipped_count:
        summary = ', '.join(skip_summary[:4])
        if len(skip_summary) > 4:
            summary += ', ...'
        messages.warning(
            request,
            f"Skipped {skipped_count} question{'s' if skipped_count != 1 else ''}: {summary}.",
        )

    return redirect('live_editor', draft_id=draft.id)


# ──────────────────────────────────────────────────────────────────────
# COPY FROM EXISTING TEST — two JSON endpoints used by the live editor
# ──────────────────────────────────────────────────────────────────────

@admin_required
@login_required
@require_http_methods(["GET"])
def api_copy_source_list(request, draft_id):
    """
    Return all published + draft tests (with their sections) that can act as
    copy sources.  The current draft itself is excluded.

    If ?section_questions=1&source_type=...&section_id=... is passed, return
    the question list for a single section instead (used by the picker modal).
    """
    from django.http import JsonResponse
    from .services.copy_import import list_source_tests, list_questions_in_source_section

    # Confirm the draft belongs to this admin (access guard)
    get_object_or_404(TestDraft, id=draft_id, created_by=request.user)

    if request.GET.get('section_questions') == '1':
        source_type = request.GET.get('source_type', '').strip()
        section_id_raw = request.GET.get('section_id', '')
        if source_type not in ('published', 'draft') or not section_id_raw:
            return JsonResponse({'questions': []})
        try:
            section_id = int(section_id_raw)
        except ValueError:
            return JsonResponse({'questions': []})
        questions = list_questions_in_source_section(source_type, section_id)
        return JsonResponse({'questions': questions})

    all_sources = list_source_tests()

    # Remove the current draft from the list so admins don't accidentally copy
    # a section into itself.
    filtered = []
    for entry in all_sources:
        if entry['source_type'] == 'draft' and entry['id'] == int(draft_id):
            continue
        filtered.append(entry)

    return JsonResponse({'sources': filtered})


@admin_required
@login_required
@require_http_methods(["POST"])
def api_copy_questions(request, draft_id):
    """
    Copy questions from a source section (published or draft) into a target
    SectionDraft of the current draft.

    POST body (form-encoded or JSON):
        target_section_id  : int
        source_type        : "published" | "draft"
        source_section_id  : int
        question_ids       : comma-separated int list, or empty → copy all
    """
    from django.http import JsonResponse
    import json as _json
    from .services.copy_import import copy_questions_into_section

    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    draft.refresh_lock(request.user)

    # Support both form-encoded and JSON request bodies
    if request.content_type and 'application/json' in request.content_type:
        try:
            payload = _json.loads(request.body)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)
    else:
        payload = request.POST

    target_section_id = payload.get('target_section_id', '')
    source_type = payload.get('source_type', '').strip()
    source_section_id = payload.get('source_section_id', '')
    question_ids_raw = payload.get('question_ids', '')

    # Validate inputs
    if not target_section_id:
        return JsonResponse({'success': False, 'error': 'target_section_id is required.'}, status=400)
    if source_type not in ('published', 'draft'):
        return JsonResponse({'success': False, 'error': 'source_type must be "published" or "draft".'}, status=400)
    if not source_section_id:
        return JsonResponse({'success': False, 'error': 'source_section_id is required.'}, status=400)

    try:
        target_section_id = int(target_section_id)
        source_section_id = int(source_section_id)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Section IDs must be integers.'}, status=400)

    # Parse optional question_ids filter
    question_ids = []
    if question_ids_raw:
        try:
            if isinstance(question_ids_raw, list):
                question_ids = [int(x) for x in question_ids_raw]
            else:
                question_ids = [int(x.strip()) for x in str(question_ids_raw).split(',') if x.strip()]
        except ValueError:
            return JsonResponse({'success': False, 'error': 'question_ids must be integers.'}, status=400)

    target_section = get_object_or_404(SectionDraft, id=target_section_id, test_draft=draft)

    result = copy_questions_into_section(
        target_section=target_section,
        source_type=source_type,
        source_section_id=source_section_id,
        question_ids=question_ids,
    )

    if result['errors']:
        return JsonResponse({'success': False, 'error': result['errors'][0]}, status=400)

    # Re-serialise the target section so the editor's JS state can update
    questions_data = [
        {
            'id': q.id,
            'order': q.order,
            'question_text': q.question_text,
            'image_url': q.question_image.url if q.question_image else None,
            'solution_text': q.solution_text,
            'solution_image_url': q.solution_image.url if q.solution_image else None,
            'options': [
                {
                    'id': opt.id,
                    'text': opt.option_text,
                    'image_url': opt.option_image.url if opt.option_image else None,
                    'is_correct': opt.is_correct,
                    'order': opt.order,
                }
                for opt in q.options.all()
            ],
        }
        for q in target_section.questions.order_by('order')
    ]

    return JsonResponse({
        'success': True,
        'copied': result['copied'],
        'skipped': result['skipped'],
        'section_id': target_section.id,
        'questions': questions_data,
    })
