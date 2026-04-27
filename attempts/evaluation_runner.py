import logging

from django.utils import timezone

from attempts.models import TestAttempt, AttemptSectionTiming
from evaluation.models import EvaluationJob
from evaluation.services import evaluate_attempt

logger = logging.getLogger(__name__)


def _materialize_section_timings(attempt: TestAttempt) -> None:
    """Merge hot AttemptSectionTiming rows into the JSON blob on the attempt.

    Moved out of the submit view so the HTTP response is not blocked by
    this DB read+write.
    """
    base_timings = {
        str(section_id): int(seconds)
        for section_id, seconds in (attempt.section_timings or {}).items()
    }
    rows = AttemptSectionTiming.objects.filter(attempt=attempt).values('section_id', 'time_spent_seconds')
    section_timings = dict(base_timings)
    for row in rows:
        section_key = str(row['section_id'])
        section_timings[section_key] = section_timings.get(section_key, 0) + int(row['time_spent_seconds'])
    TestAttempt.objects.filter(pk=attempt.pk).update(section_timings=section_timings)
    attempt.section_timings = section_timings


def process_attempt_evaluation(attempt_id: int, job_id: int | None = None) -> None:
    job = None
    if job_id is not None:
        job = EvaluationJob.objects.filter(pk=job_id).first()

    attempt = TestAttempt.objects.select_related('test', 'user').get(pk=attempt_id)
    if attempt.evaluation_state == TestAttempt.EVAL_SUCCESS:
        if job:
            job.status = EvaluationJob.STATUS_SUCCESS
            job.started_at = job.started_at or timezone.now()
            job.finished_at = timezone.now()
            job.error_message = ''
            job.save(update_fields=['status', 'started_at', 'finished_at', 'error_message'])
        return

    # Materialize section timings before evaluating — moved from the submit
    # view so the HTTP response is not blocked by this DB read+write.
    try:
        _materialize_section_timings(attempt)
    except Exception:
        logger.exception('Failed to materialize section timings for attempt %s', attempt_id)

    if job:
        job.status = EvaluationJob.STATUS_RUNNING
        job.started_at = timezone.now()
        job.error_message = ''
        job.save(update_fields=['status', 'started_at', 'error_message'])

    attempt.evaluation_state = TestAttempt.EVAL_RUNNING
    attempt.evaluation_started_at = timezone.now()
    attempt.evaluation_error = ''
    attempt.save(update_fields=['evaluation_state', 'evaluation_started_at', 'evaluation_error'])

    try:
        evaluate_attempt(attempt)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"[:500]
        if job:
            job.status = EvaluationJob.STATUS_FAILED
            job.finished_at = timezone.now()
            job.error_message = error_text
            job.retry_count = job.retry_count + 1
            job.save(update_fields=['status', 'finished_at', 'error_message', 'retry_count'])
        TestAttempt.objects.filter(pk=attempt_id).update(
            evaluation_state=TestAttempt.EVAL_FAILED,
            evaluation_finished_at=timezone.now(),
            evaluation_error=error_text,
        )
        raise

    if job:
        job.status = EvaluationJob.STATUS_SUCCESS
        job.finished_at = timezone.now()
        job.error_message = ''
        job.save(update_fields=['status', 'finished_at', 'error_message'])

    TestAttempt.objects.filter(pk=attempt_id).update(
        evaluation_state=TestAttempt.EVAL_SUCCESS,
        evaluation_finished_at=timezone.now(),
        evaluation_error='',
    )