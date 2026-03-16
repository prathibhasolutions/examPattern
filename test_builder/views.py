from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction, models
from django.utils.text import slugify
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import TestDraft, SectionDraft, QuestionDraft, OptionDraft
from testseries.models import TestSeries, TestSeriesExamSection, TestSeriesHighlight, Test, Section, SeriesSection, SeriesSubsection
from questions.models import Question, Option


# Permission check: Only staff/admin users can access builder
def is_admin(user):
    """Check if user is staff/admin"""
    return user.is_staff and user.is_superuser


def admin_required(view_func):
    """Decorator to require admin access"""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_staff and request.user.is_superuser):
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
    
    published_by_series = defaultdict(list)
    for draft in published_qs.select_related('series'):
        published_by_series[draft.series].append(draft)
    
    # Get all series for suggestions
    all_series = TestSeries.objects.all()
    
    return render(request, 'test_builder/dashboard.html', {
        'drafts_by_series': dict(drafts_by_series),
        'published_by_series': dict(published_by_series),
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
@transaction.atomic
def publish_test(request, draft_id):
    """Convert draft to actual test or update existing published test"""
    from datetime import datetime
    
    draft = get_object_or_404(TestDraft, id=draft_id, created_by=request.user)
    
    # Check if locked by another admin
    if not draft.can_edit(request.user):
        messages.error(request, f"❌ This test is currently being edited by {draft.locked_by.username}. "
                                f"Please wait until they finish. Lock will auto-expire after 30 minutes of inactivity.")
        return redirect('builder_dashboard')
    
    if draft.is_published:
        messages.warning(request, "This test is already published!")
        return redirect('builder_dashboard')

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
            is_active=True
        )
    
    # Create sections
    for section_draft in draft.sections.all():
        # Calculate section time limit in seconds if sectional timing is enabled
        section_time_seconds = 0
        if draft.use_sectional_timing and section_draft.time_limit_minutes:
            section_time_seconds = section_draft.time_limit_minutes * 60
        
        section = Section.objects.create(
            test=test,
            name=section_draft.name,
            order=section_draft.order,
            time_limit_seconds=section_time_seconds
        )
        
        # Create questions
        for question_draft in section_draft.questions.all():
            # Validation during publish: Question must have text or image
            if not question_draft.question_text and not question_draft.question_image:
                messages.error(request, f"❌ Cannot publish: Question in '{section_draft.name}' has neither text nor image.")
                return redirect('builder_dashboard')
            
            question = Question.objects.create(
                section=section,
                text=question_draft.question_text,
                image=question_draft.question_image,
                explanation=question_draft.solution_text,
                solution_image=question_draft.solution_image
            )
            
            # Validation: Question must have at least one option
            if question_draft.options.count() == 0:
                messages.error(request, f"❌ Cannot publish: Question in '{section_draft.name}' has no options.")
                return redirect('builder_dashboard')
            
            # Validation: Question must have exactly one correct answer
            correct_options_count = question_draft.options.filter(is_correct=True).count()
            if correct_options_count == 0:
                messages.error(request, f"❌ Cannot publish: A question in '{section_draft.name}' has no correct answer selected.")
                return redirect('builder_dashboard')
            elif correct_options_count > 1:
                messages.error(request, f"❌ Cannot publish: A question in '{section_draft.name}' has {correct_options_count} correct answers. Only one correct answer is allowed per question.")
                return redirect('builder_dashboard')
            
            # Create options
            for option_draft in question_draft.options.all():
                # Validation: Option must have text or image
                if not option_draft.option_text and not option_draft.option_image:
                    messages.error(request, f"❌ Cannot publish: An option in '{section_draft.name}' has neither text nor image.")
                    return redirect('builder_dashboard')
                
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
    
    action_type = "updated" if published_test else "published"
    messages.success(request, f"Test '{test.name}' {action_type} successfully! Students can now take this test.")
    return redirect('builder_dashboard')


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
        return redirect('manage_sections', draft_id=draft.id)
    
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
