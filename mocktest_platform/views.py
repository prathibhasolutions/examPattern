from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
import os


try:
    from io import BytesIO
    PDF_AVAILABLE = True
except Exception as e:
    print(f"PDF_AVAILABLE Error: {e}")
    PDF_AVAILABLE = False

from testseries.models import Test, TestSeries, SeriesSection, SeriesSubsection
from django.db.models import Count, Q, Prefetch, Avg
from attempts.models import TestAttempt, Answer, AttemptSectionTiming
from evaluation.models import EvaluationResult
from testseries.models import TestSeriesExamSection, TestSeriesHighlight

@require_http_methods(["GET"])
def about_page(request):
    return render(request, 'about.html')


@require_http_methods(["GET"])
def series_suggest(request):
    """Return JSON list of active test series names matching query (for autocomplete)."""
    q = request.GET.get('q', '').strip()
    qs = TestSeries.objects.filter(is_active=True)
    if q:
        qs = qs.filter(name__icontains=q)
    results = list(qs.values('name', 'slug')[:10])
    return JsonResponse(results, safe=False)


@require_http_methods(["GET"])
def tests_list(request):
    """Display list of test series."""
    series = (
        TestSeries.objects
        .filter(is_active=True)
        .annotate(test_count=Count('tests', filter=Q(tests__is_active=True)))
    )
    return render(request, 'tests_list.html', {'series': series})


@require_http_methods(["GET"])
def tests_series_detail(request, slug):
    """Display tests within a series with sections as main tabs and subsections as sub-tabs."""
    from django.db.models import Prefetch, Count, Q
    from test_builder.models import TestDraft

    series = get_object_or_404(TestSeries.objects.filter(is_active=True), slug=slug)

    # Get all sections for this series (these will be main nav pills)
    sections = (
        SeriesSection.objects
        .filter(series=series, is_active=True)
        .prefetch_related(
            Prefetch(
                'subsections',
                queryset=SeriesSubsection.objects.filter(is_active=True).order_by('name')
            )
        )
        .order_by('name')  # Alphabetically sorted
    )

    # Get all tests for the entire series (for "All Tests" section)
    all_tests = (
        Test.objects
        .filter(is_active=True, series=series)
        .annotate(question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True)))
        .order_by('name')
    )

    # Organize data for each section
    sectional_data = []
    for section in sections:
        # Check if this is "All Tests" section (case-insensitive)
        if section.name.lower() == 'all tests':
            # For "All Tests" section, include all tests in the series
            all_drafts = []
            if request.user.is_staff:
                all_drafts = list(TestDraft.objects.filter(
                    series=series, is_published=False
                ).order_by('name'))
            sectional_data.append({
                'section': section,
                'subsections': [],
                'tests': all_tests,
                'drafts': all_drafts,
                'is_all_tests': True
            })
        else:
            # Get tests directly under this section (no subsection)
            section_tests = Test.objects.filter(
                series=series,
                series_section=section,
                series_subsection__isnull=True,
                is_active=True
            ).annotate(
                question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
            ).order_by('name')

            # Draft tests for this section (admin only)
            section_drafts = []
            if request.user.is_staff:
                section_drafts = list(TestDraft.objects.filter(
                    series=series,
                    series_section=section,
                    series_subsection__isnull=True,
                    is_published=False,
                ).order_by('name'))

            # Get subsections with their tests
            subsections_with_tests = []
            for subsection in section.subsections.all():
                subsection_tests = Test.objects.filter(
                    series=series,
                    series_section=section,
                    series_subsection=subsection,
                    is_active=True
                ).annotate(
                    question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
                ).order_by('name')

                subsection_drafts = []
                if request.user.is_staff:
                    subsection_drafts = list(TestDraft.objects.filter(
                        series=series,
                        series_section=section,
                        series_subsection=subsection,
                        is_published=False,
                    ).order_by('name'))

                subsections_with_tests.append({
                    'subsection': subsection,
                    'tests': subsection_tests,
                    'drafts': subsection_drafts,
                })
            
            sectional_data.append({
                'section': section,
                'subsections': subsections_with_tests,
                'tests': section_tests,
                'drafts': section_drafts,
                'is_all_tests': False
            })

    # Build per-test attempt info for authenticated users
    attempt_map = {}
    if request.user.is_authenticated:
        from attempts.models import TestAttempt
        all_test_ids = list(all_tests.values_list('id', flat=True))
        user_attempts = TestAttempt.objects.filter(
            user=request.user, test_id__in=all_test_ids
        ).order_by('test_id', '-attempt_number')
        for attempt in user_attempts:
            tid = attempt.test_id
            if tid not in attempt_map:
                attempt_map[tid] = {
                    'submitted_count': 0,
                    'in_progress_id': None,
                    'latest_submitted_id': None,
                }
            if attempt.status == TestAttempt.STATUS_IN_PROGRESS and attempt_map[tid]['in_progress_id'] is None:
                attempt_map[tid]['in_progress_id'] = attempt.id
            elif attempt.status == TestAttempt.STATUS_SUBMITTED:
                attempt_map[tid]['submitted_count'] += 1
                if attempt_map[tid]['latest_submitted_id'] is None:
                    attempt_map[tid]['latest_submitted_id'] = attempt.id

    # Build a map of test_id → draft_id so the edit modal can link to live editor
    test_draft_map = {}
    if request.user.is_staff:
        all_test_ids = list(all_tests.values_list('id', flat=True))
        linked_drafts = TestDraft.objects.filter(
            published_test_id__in=all_test_ids
        ).values('published_test_id', 'id')
        test_draft_map = {d['published_test_id']: d['id'] for d in linked_drafts}

    has_access = True
    if request.user.is_authenticated and not request.user.is_staff:
        from payments.utils import user_has_series_access
        has_access, _ = user_has_series_access(request.user, series)

    return render(request, 'testseries/series_tests.html', {
        'series': series,
        'sectional_data': sectional_data,
        'all_tests': all_tests,
        'attempt_map': attempt_map,
        'test_draft_map': test_draft_map,
        'has_access': has_access,
    })


@require_http_methods(["GET"])
def tests_series_about(request, slug):
    """Display exam details for a test series."""
    series = get_object_or_404(TestSeries.objects.filter(is_active=True), slug=slug)
    sections = list(series.exam_sections.all().order_by("order", "id"))
    if not sections:
        sections = [
            TestSeriesExamSection(
                series=series,
                title="Coming soon",
                body="Exam details will be published here once they are available.",
            )
        ]

    highlights = list(series.highlights.all().order_by("order", "id"))

    context = {
        "series": series,
        "tagline": series.description or "Exam overview and key information",
        "sections": sections,
        "highlights": highlights,
    }
    return render(request, "testseries/series_about.html", context)


@login_required
@require_http_methods(["GET"])
def test_instructions(request, test_id):
    """Display test instructions before starting the test."""
    test = get_object_or_404(Test, id=test_id, is_active=True)

    # ── Access gate ───────────────────────────────────────────────────────────
    from payments.utils import user_has_series_access
    has_access, _ = user_has_series_access(request.user, test.series)
    if not has_access:
        return redirect('series_payment', slug=test.series.slug)
    # ─────────────────────────────────────────────────────────────────────────

    # Single query: fetch all sections with annotated question counts
    sections = (
        test.sections
        .filter(is_active=True)
        .annotate(active_question_count=Count('questions', filter=Q(questions__is_active=True)))
        .order_by('order')
    )

    total_questions = 0
    total_marks = 0
    sections_data = []

    for section in sections:
        question_count = section.active_question_count
        total_questions += question_count

        if section.marks_per_question is not None:
            section_marks = question_count * section.marks_per_question
        else:
            section_marks = question_count * test.marks_per_question
        total_marks += section_marks

        if test.use_sectional_timing and section.time_limit_seconds:
            duration_minutes = section.time_limit_seconds // 60
        elif section.time_limit_seconds:
            duration_minutes = section.time_limit_seconds // 60
        else:
            duration_minutes = "No limit"

        sections_data.append({
            'name': section.name,
            'question_count': question_count,
            'marks': section_marks,
            'duration_minutes': duration_minutes,
        })

    if not sections_data:
        total_questions = test.questions.filter(is_active=True).count()
        total_marks = total_questions * test.marks_per_question

    test_duration_minutes = test.duration_seconds // 60 if test.duration_seconds else 0
    
    return render(request, 'test_instructions.html', {
        'test': test,
        'sections': sections_data,
        'total_questions': total_questions,
        'total_marks': total_marks,
        'test_duration_minutes': test_duration_minutes,
        'use_sectional_timing': test.use_sectional_timing,
    })


@login_required
@require_http_methods(["GET"])
def test_interface(request, test_id):
    """Display test-taking interface."""
    test = get_object_or_404(Test, id=test_id, is_active=True)
    attempt_id = request.GET.get('attempt_id')
    
    if not attempt_id:
        return render(request, 'test_interface.html', {
            'test_id': test_id,
            'attempt_id': None,
            'error': 'No active attempt found. Please start the test from the tests list.',
        })
    
    # Verify the attempt belongs to this user
    attempt = get_object_or_404(TestAttempt, id=attempt_id, user=request.user, test=test)
    
    # If attempt is already submitted, redirect to results page
    if attempt.status == TestAttempt.STATUS_SUBMITTED:
        return redirect('results_page', attempt_id=attempt_id)
    
    return render(request, 'test_interface.html', {
        'test_id': test_id,
        'attempt_id': attempt_id,
        'test': test,
        'now': timezone.now(),
    })


@login_required
@require_http_methods(["GET"])
def test_results_analysis(request, test_id):
    """Display all attempts and analysis for a test."""
    test = get_object_or_404(Test, id=test_id, is_active=True)
    
    # Get all attempts by current user for this test
    attempts = TestAttempt.objects.filter(
        user=request.user, test=test
    ).order_by('attempt_number')
    
    if not attempts.exists():
        return render(request, 'test_results_analysis.html', {
            'test': test,
            'attempts': [],
            'no_attempts': True,
        })
    
    # Get evaluation data for each attempt
    attempts_data = []
    for attempt in attempts:
        evaluation = None
        try:
            evaluation = EvaluationResult.objects.get(attempt=attempt)
        except EvaluationResult.DoesNotExist:
            pass
        
        attempts_data.append({
            'attempt': attempt,
            'evaluation': evaluation,
        })
    
    return render(request, 'test_results_analysis.html', {
        'test': test,
        'attempts_data': attempts_data,
        'no_attempts': False,
    })

@login_required
@require_http_methods(["GET"])
def attempt_results(request, attempt_id):
    """Display test results and analysis."""
    if request.user.is_staff or request.user.is_superuser:
        attempt = get_object_or_404(TestAttempt, id=attempt_id)
    else:
        attempt = get_object_or_404(TestAttempt, id=attempt_id, user=request.user)
    viewing_as_admin = request.user != attempt.user
    
    # Get evaluation results
    evaluation = None
    try:
        evaluation = EvaluationResult.objects.get(attempt=attempt)
        
        # Calculate additional metrics
        total_questions = 0
        attempted_count = 0
        correct_count = 0
        
        # Calculate section accuracies and aggregate stats
        for section_id, data in evaluation.section_scores.items():
            total_questions += data.get('total_questions', 0)
            attempted = data.get('correct', 0) + data.get('incorrect', 0)
            attempted_count += attempted
            correct_count += data.get('correct', 0)
            
            # Calculate percentage and accuracy for each section
            total_marks = Decimal(data.get('total_marks', 0)) if 'total_marks' in data else None
            score = Decimal(data.get('score', 0))
            
            if total_marks and total_marks > 0:
                data['percentage'] = float((score / total_marks) * 100)
            else:
                data['percentage'] = 0.0
                
            if attempted > 0:
                data['accuracy'] = (data.get('correct', 0) / attempted) * 100
            else:
                data['accuracy'] = 0.0
        
        # Add aggregate metrics to evaluation
        evaluation.total_questions = total_questions
        evaluation.attempted_count = attempted_count
        
        # Calculate overall accuracy (correct/attempted)
        if attempted_count > 0:
            evaluation.accuracy = (correct_count / attempted_count) * 100
        else:
            evaluation.accuracy = 0.0
        
        # Calculate score percentage
        if evaluation.total_score is not None and attempt.test:
            from django.db.models import Sum, Case, When, F
            from questions.models import Question

            # Single aggregation query instead of a Python loop over all questions
            agg = (
                Question.objects
                .filter(section__test=attempt.test, is_active=True)
                .select_related('section')
                .aggregate(
                    total=Sum(
                        Case(
                            When(marks_override__isnull=False, then=F('marks_override')),
                            When(section__marks_per_question__isnull=False, then=F('section__marks_per_question')),
                            default=attempt.test.marks_per_question,
                        )
                    )
                )
            )
            total_possible_marks = Decimal(str(agg['total'] or 0))

            evaluation.max_marks = float(total_possible_marks)
            evaluation.percentage = (
                float((evaluation.total_score / total_possible_marks) * 100)
                if total_possible_marks > 0
                else 0.0
            )
        else:
            evaluation.max_marks = 0
            evaluation.percentage = 0.0
            
        # Get total attempts for rank display (only first attempts, excluding admins)
        evaluation.total_attempts = TestAttempt.objects.filter(
            test=attempt.test,
            status=TestAttempt.STATUS_SUBMITTED,
            attempt_number=1,
            user__is_staff=False,
            user__is_superuser=False,
        ).count()
        
        # Only calculate rank and percentile for first attempts of non-admin users
        if attempt.attempt_number == 1 and not (attempt.user.is_staff or attempt.user.is_superuser):
            # Calculate rank among first attempts only (excluding admins)
            better_scores = EvaluationResult.objects.filter(
                attempt__test=attempt.test,
                attempt__status=TestAttempt.STATUS_SUBMITTED,
                attempt__attempt_number=1,
                attempt__user__is_staff=False,
                attempt__user__is_superuser=False,
                total_score__gt=evaluation.total_score
            ).count()
            
            evaluation.rank = better_scores + 1
            
            # Calculate percentile among first attempts only
            # Percentile = ((total - rank + 1) / total) * 100
            if evaluation.total_attempts > 0:
                percentile_value = ((evaluation.total_attempts - evaluation.rank + 1) / evaluation.total_attempts) * 100
                evaluation.percentile = float(percentile_value)
            else:
                evaluation.percentile = 0.0
        else:
            # For admin attempts or second attempts, don't calculate rank/percentile
            evaluation.rank = None
            evaluation.percentile = None
        
    except EvaluationResult.DoesNotExist:
        pass
    
    # Get top 10 rankings for this test (only first attempts, excluding admins)
    top_rankings = []
    if evaluation:
        top_rankings = (
            EvaluationResult.objects
            .filter(
                attempt__test=attempt.test,
                attempt__status=TestAttempt.STATUS_SUBMITTED,
                attempt__attempt_number=1,
                attempt__user__is_staff=False,
                attempt__user__is_superuser=False,
            )
            .select_related('attempt__user')
            .order_by('-total_score', 'evaluated_at')[:10]
        )
    
    # Get all attempts for this test by the attempt owner (for attempt switcher)
    all_attempts = (
        TestAttempt.objects
        .filter(user=attempt.user, test=attempt.test, status=TestAttempt.STATUS_SUBMITTED)
        .order_by('-attempt_number')
    )
    
    # Calculate timing data
    # Use attempt.duration_seconds as the authoritative total — it is computed at
    # submission time as (test_duration - time_remaining_seconds) and is always
    # accurate, even when the student skips navigation (heartbeats never fire).
    # section_timings is a JSONField with string keys: {"<section_id>": seconds}
    # which matches what the JS lookup expects via data-section-id attributes.
    total_time_spent = attempt.duration_seconds or 0
    section_times = attempt.section_timings or {}   # already string-keyed
    if not section_times:
        section_times = {
            str(row['section_id']): row['time_spent_seconds']
            for row in AttemptSectionTiming.objects.filter(attempt=attempt).values('section_id', 'time_spent_seconds')
        }
    test_duration = attempt.test.duration_seconds or 0

    timing_data = {
        'total_time_spent': total_time_spent,
        'test_duration': test_duration,
        'section_times': section_times,
    }
    
    return render(request, 'results.html', {
        'attempt': attempt,
        'evaluation': evaluation,
        'top_rankings': top_rankings,
        'is_second_attempt': attempt.attempt_number > 1,
        'all_attempts': all_attempts,
        'max_marks': evaluation.max_marks if evaluation else 0,
        'timing_data': timing_data,
        'viewing_as_admin': viewing_as_admin,
    })


# Alias for URL pattern
results_page = attempt_results


@login_required
@require_http_methods(["GET"])
def submitted_page(request, attempt_id):
    """
    Intermediate page shown immediately after a student submits.
    Displays a success animation and polls /api/v1/attempts/{id}/evaluation_status/
    every few seconds with backoff. Redirects to results page once evaluation is ready.
    """
    if request.user.is_staff or request.user.is_superuser:
        attempt = get_object_or_404(TestAttempt, id=attempt_id)
    else:
        attempt = get_object_or_404(TestAttempt, id=attempt_id, user=request.user)

    # If evaluation already done (e.g. user refreshed), go straight to results
    if EvaluationResult.objects.filter(attempt=attempt).exists():
        return redirect('results_page', attempt_id=attempt_id)

    return render(request, 'submitted.html', {
        'attempt': attempt,
        'attempt_id': attempt_id,
    })


@login_required
@require_http_methods(["GET"])
def download_result_pdf(request, attempt_id):
    """Generate and download test result as PDF."""
    # Import WeasyPrint here to catch errors
    try:
        from weasyprint import HTML
    except Exception as e:
        error_msg = f"PDF generation failed: {type(e).__name__}: {str(e)}"
        print(error_msg)
        return HttpResponse(error_msg, status=503)
    
    if request.user.is_staff or request.user.is_superuser:
        attempt = get_object_or_404(TestAttempt, id=attempt_id)
    else:
        attempt = get_object_or_404(TestAttempt, id=attempt_id, user=request.user)

    # Get evaluation results
    evaluation = None
    try:
        evaluation = EvaluationResult.objects.get(attempt=attempt)
    except EvaluationResult.DoesNotExist:
        return HttpResponse("Results not ready yet", status=400)
    
    # Get logo path for PDF
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'prathibha-logo.png')
    
    # Get all questions for this test with their options
    from questions.models import Question
    questions = (
        Question.objects
        .filter(section__test=attempt.test)
        .select_related('section')
        .prefetch_related('options')
        .order_by('section__order', 'id')
    )
    
    # Get all answers for this attempt
    from attempts.models import Answer
    answers = Answer.objects.filter(attempt=attempt).prefetch_related('selected_options')
    
    # Build dictionaries for user answers and correct answers
    user_answers = {}
    correct_answers = {}
    
    for answer in answers:
        question_id = answer.question_id
        # User's answer (first selected option if multiple)
        if answer.selected_options.exists():
            user_answers[question_id] = answer.selected_options.first().id
        
        # Correct answer
        correct_option = answer.question.options.filter(is_correct=True).first()
        if correct_option:
            correct_answers[question_id] = correct_option.id
    
    # Render HTML template for PDF
    html_string = render_to_string('result_pdf.html', {
        'attempt': attempt,
        'evaluation': evaluation,
        'request': request,
        'logo_path': logo_path,
        'questions': questions,
        'user_answers': user_answers,
        'correct_answers': correct_answers,
    })
    
    # Generate PDF using WeasyPrint
    try:
        pdf_bytes = HTML(string=html_string, base_url=settings.BASE_DIR).write_pdf()
    except Exception as e:
        return HttpResponse(f"Error generating PDF: {e}", status=500)
    
    # Return PDF as download
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="{attempt.user.username}_{attempt.test.series.name}_{attempt.test.name}_result.pdf"'
    )
    return response

@login_required
@require_http_methods(["GET"])
def review_solutions(request, attempt_id):
    """Display test review with solutions after submission."""
    if request.user.is_staff or request.user.is_superuser:
        attempt = get_object_or_404(TestAttempt, id=attempt_id)
    else:
        attempt = get_object_or_404(TestAttempt, id=attempt_id, user=request.user)
    viewing_as_admin = request.user != attempt.user
    
    # Verify attempt is submitted
    if attempt.status != TestAttempt.STATUS_SUBMITTED:
        return redirect('results_page', attempt_id=attempt_id)
    
    from questions.models import Question

    # Load all questions for this test and map answers
    questions = (
        Question.objects
        .filter(section__test=attempt.test)
        .select_related('section')
        .prefetch_related('options')
        .order_by('section__order', 'id')
    )

    answers = (
        attempt.answers.all()
        .select_related('question', 'question__section')
        .prefetch_related('selected_options')
    )
    answers_by_question = {answer.question_id: answer for answer in answers}

    # Calculate average time per question across all attempts of this test
    avg_times = Answer.objects.filter(
        attempt__test=attempt.test,
        attempt__status=TestAttempt.STATUS_SUBMITTED,
        time_spent_seconds__gt=0  # exclude unvisited/untracked answers so they don't drag average to 0
    ).values('question_id').annotate(
        avg_time=Avg('time_spent_seconds')
    )
    avg_times_by_question = {item['question_id']: item['avg_time'] for item in avg_times}

    sections = list(attempt.test.sections.all().order_by('order', 'id'))
    section_counters = {section.id: 1 for section in sections}

    sections_payload = [
        {
            'id': section.id,
            'name': section.name,
            'order': section.order,
        }
        for section in sections
    ]

    questions_payload = []
    for question in questions:
        answer = answers_by_question.get(question.id)
        selected_ids = []
        response_text = ''

        if answer:
            selected_ids = list(answer.selected_options.values_list('id', flat=True))
            response_text = answer.response_text or ''

        is_answered = bool(selected_ids) or bool(response_text.strip())
        is_correct = bool(answer and answer.marks_obtained is not None and answer.marks_obtained > 0)
        status = 'unanswered'
        if is_answered:
            status = 'correct' if is_correct else 'incorrect'
        # Bonus questions: override status so students see they received bonus marks
        if question.is_bonus:
            status = 'bonus'

        question_number = section_counters[question.section_id]
        section_counters[question.section_id] += 1

        options_payload = [
            {
                'id': opt.id,
                'text': opt.text or '',
                'image_url': opt.image.url if opt.image else '',
                'is_correct': opt.is_correct,
            }
            for opt in question.options.all()
        ]

        questions_payload.append({
            'id': question.id,
            'section_id': question.section_id,
            'section_name': question.section.name,
            'section_order': question.section.order,
            'question_number': question_number,
            'text': question.text or '',
            'extracted_text': question.extracted_text or '',
            'is_math': question.is_math,
            'image_url': question.image.url if question.image else '',
            'options': options_payload,
            'user_option_ids': selected_ids,
            'response_text': response_text,
            'status': status,
            'is_bonus': question.is_bonus,
            'solution_explanation': question.explanation or '',
            'solution_image_url': question.solution_image.url if question.solution_image else '',
            'time_spent_seconds': answer.time_spent_seconds if answer else 0,
            'average_time_seconds': round(avg_times_by_question.get(question.id, 0)) if avg_times_by_question.get(question.id) else 0,
        })

    max_marks = Decimal('0')
    for question in questions:
        if question.marks_override:
            max_marks += question.marks_override
        elif question.section.marks_per_question:
            max_marks += question.section.marks_per_question
        else:
            max_marks += attempt.test.marks_per_question

    review_payload = {
        'sections': sections_payload,
        'questions': questions_payload,
    }

    all_attempts = TestAttempt.objects.filter(
        user=attempt.user,
        test=attempt.test,
        status=TestAttempt.STATUS_SUBMITTED,
    ).order_by('attempt_number')

    return render(request, 'review_solutions.html', {
        'attempt': attempt,
        'review_payload': review_payload,
        'all_attempts': all_attempts,
        'max_marks': max_marks,
        'viewing_as_admin': viewing_as_admin,
    })


def privacy_policy(request):
    return render(request, 'privacy_policy.html')


def terms_of_service(request):
    return render(request, 'terms_of_service.html')


def refund_policy(request):
    return render(request, 'refund_policy.html')
