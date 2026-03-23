from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from attempts.models import TestAttempt, Answer
from .models import EvaluationResult


DECIMAL_ZERO = Decimal('0.00')


def _get_marking_scheme(question):
    test = question.section.test

    if question.marks_override is not None:
        marks = question.marks_override
    elif question.section.marks_per_question is not None:
        marks = question.section.marks_per_question
    else:
        marks = test.marks_per_question

    if question.negative_marks_override is not None:
        negative = question.negative_marks_override
    elif question.section.negative_marks_per_question is not None:
        negative = question.section.negative_marks_per_question
    else:
        negative = test.negative_marks_per_question

    return Decimal(marks), Decimal(negative)


def _score_answer(answer):
    question = answer.question
    marks, negative = _get_marking_scheme(question)

    # Objective question with options
    if question.options.exists():
        correct_ids = {opt.id for opt in question.options.all() if opt.is_correct}
        selected_ids = {opt.id for opt in answer.selected_options.all()}

        if not selected_ids:
            return DECIMAL_ZERO, 'unanswered'

        if selected_ids == correct_ids:
            return marks, 'correct'

        return -negative, 'incorrect'

    # Subjective question (not auto-evaluated)
    if answer.response_text and answer.response_text.strip():
        return DECIMAL_ZERO, 'subjective'

    return DECIMAL_ZERO, 'unanswered'


@transaction.atomic
def evaluate_attempt(attempt: TestAttempt) -> EvaluationResult:
    answers = (
        Answer.objects
        .filter(attempt=attempt)
        .select_related('question__section__test')
        .prefetch_related('selected_options', 'question__options')
    )

    section_scores = {}
    total_score = DECIMAL_ZERO
    updates = []

    for answer in answers:
        section = answer.question.section
        section_id = str(section.id)

        if section_id not in section_scores:
            section_scores[section_id] = {
                'section_id': section.id,
                'section_name': section.name,
                'score': DECIMAL_ZERO,
                'correct': 0,
                'incorrect': 0,
                'unanswered': 0,
                'subjective': 0,
                'total_questions': 0,
            }

        marks, status = _score_answer(answer)
        answer.marks_obtained = marks
        updates.append(answer)

        section_scores[section_id]['score'] = section_scores[section_id]['score'] + marks
        section_scores[section_id]['total_questions'] += 1

        if status == 'correct':
            section_scores[section_id]['correct'] += 1
        elif status == 'incorrect':
            section_scores[section_id]['incorrect'] += 1
        elif status == 'subjective':
            section_scores[section_id]['subjective'] += 1
        else:
            section_scores[section_id]['unanswered'] += 1

        total_score += marks

    if updates:
        Answer.objects.bulk_update(updates, ['marks_obtained'])

    attempt.score = total_score
    attempt.save(update_fields=['score'])

    # Rank and percentile among submitted attempts for this test
    # Only consider first attempts (attempt_number=1) for fair ranking
    # Exclude staff/superuser attempts from the ranking pool
    submitted = TestAttempt.objects.filter(
        test=attempt.test,
        status=TestAttempt.STATUS_SUBMITTED,
        score__isnull=False,
        attempt_number=1,  # Only count first attempts
        user__is_staff=False,
        user__is_superuser=False,
    )

    # Only calculate rank/percentile for first attempts of non-admin users
    if attempt.attempt_number == 1 and not (attempt.user.is_staff or attempt.user.is_superuser):
        total_attempts = submitted.count()
        higher_count = submitted.filter(score__gt=total_score).count()

        rank = higher_count + 1 if total_attempts > 0 else None
        # Percentile = ((total - rank + 1) / total) * 100
        # For rank 1/1: ((1 - 1 + 1) / 1) * 100 = 100%
        # For rank 1/10: ((10 - 1 + 1) / 10) * 100 = 100%
        # For rank 5/10: ((10 - 5 + 1) / 10) * 100 = 60%
        percentile = (
            (Decimal(total_attempts - rank + 1) / Decimal(total_attempts) * Decimal('100.00'))
            if total_attempts > 0 and rank is not None
            else None
        )
    else:
        # For second attempts, don't assign rank or percentile
        rank = None
        percentile = None

    # Convert Decimal scores for JSON storage
    serializable_section_scores = {}
    for key, data in section_scores.items():
        serializable_section_scores[key] = {
            **data,
            'score': str(data['score']),
        }

    result, _ = EvaluationResult.objects.update_or_create(
        attempt=attempt,
        defaults={
            'total_score': total_score,
            'section_scores': serializable_section_scores,
            'rank': rank,
            'percentile': percentile,
        },
    )

    return result
