import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db.models import Exists, OuterRef

from attempts.evaluation_runner import process_attempt_evaluation
from evaluation.models import EvaluationJob
from attempts.models import TestAttempt
from evaluation.models import EvaluationResult


logger = logging.getLogger(__name__)

# ── Background recalculation deduplication ──────────────────────────────────
# Tracks which test IDs currently have a recalculation running so we never
# start two concurrent recalculations for the same test.
# _RECALC_PENDING: if a recalc is already running when a new one is requested,
# we can't skip the new request — evaluation jobs are still completing and the
# running recalc started with stale data.  Instead we mark it "pending" so
# that when the current run finishes it triggers one final re-run that will
# see all evaluations that completed in the meantime.
_RECALC_LOCK = threading.Lock()
_RECALC_IN_PROGRESS: set = set()
_RECALC_PENDING: set = set()


def _resolve_local_workers() -> int:
    configured = max(1, int(getattr(settings, 'EVALUATION_LOCAL_MAX_WORKERS', 2)))
    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    if 'sqlite' in engine and configured > 4:
        return 4
    return configured


EVALUATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=_resolve_local_workers(),
    thread_name_prefix='eval-worker',
)
_WORKER_STARTED = False
_WAKE_EVENT = threading.Event()
_POLL_INTERVAL_SECONDS = 1.0


def _run_local(attempt_id: int, job_id: int | None = None) -> None:
    def _worker():
        from django.db import connection

        try:
            process_attempt_evaluation(attempt_id, job_id=job_id)
        except Exception:
            logger.exception('Background evaluate_attempt failed for attempt %s', attempt_id)
        finally:
            connection.close()

    EVALUATION_EXECUTOR.submit(_worker)


def _claim_next_pending_job() -> EvaluationJob | None:
    candidate_id = (
        EvaluationJob.objects
        .filter(status=EvaluationJob.STATUS_PENDING)
        .order_by('queued_at', 'id')
        .values_list('id', flat=True)
        .first()
    )
    if not candidate_id:
        return None

    claimed = EvaluationJob.objects.filter(
        id=candidate_id,
        status=EvaluationJob.STATUS_PENDING,
    ).update(status=EvaluationJob.STATUS_RUNNING)
    if not claimed:
        return None

    return EvaluationJob.objects.select_related('attempt').get(id=candidate_id)


def _reconcile_pending_attempts() -> None:
    open_job_subquery = EvaluationJob.objects.filter(
        attempt_id=OuterRef('pk'),
        status__in=[EvaluationJob.STATUS_PENDING, EvaluationJob.STATUS_RUNNING],
    )
    pending_attempts = (
        TestAttempt.objects
        .filter(status=TestAttempt.STATUS_SUBMITTED, evaluation_state=TestAttempt.EVAL_PENDING)
        .annotate(has_open_job=Exists(open_job_subquery))
        .filter(has_open_job=False)
        .values_list('id', flat=True)
    )
    for attempt_id in pending_attempts:
        EvaluationJob.objects.create(
            attempt_id=attempt_id,
            status=EvaluationJob.STATUS_PENDING,
            worker_backend='local',
            error_message='Recovered pending attempt after restart',
        )


def _reconcile_failed_attempts() -> None:
    if not getattr(settings, 'EVALUATION_AUTO_RETRY_FAILED', True):
        return

    max_retries = max(1, int(getattr(settings, 'EVALUATION_LOCAL_MAX_RETRIES', 2)))
    open_job_subquery = EvaluationJob.objects.filter(
        attempt_id=OuterRef('pk'),
        status__in=[EvaluationJob.STATUS_PENDING, EvaluationJob.STATUS_RUNNING],
    )
    failed_attempts = (
        TestAttempt.objects
        .filter(status=TestAttempt.STATUS_SUBMITTED, evaluation_state=TestAttempt.EVAL_FAILED)
        .annotate(has_open_job=Exists(open_job_subquery))
        .filter(has_open_job=False)
        .values_list('id', flat=True)
    )
    for attempt_id in failed_attempts:
        if EvaluationResult.objects.filter(attempt_id=attempt_id).exists():
            continue
        failed_count = EvaluationJob.objects.filter(
            attempt_id=attempt_id,
            status=EvaluationJob.STATUS_FAILED,
        ).count()
        if failed_count >= max_retries:
            continue
        EvaluationJob.objects.create(
            attempt_id=attempt_id,
            status=EvaluationJob.STATUS_PENDING,
            worker_backend='local',
            retry_count=failed_count,
            error_message='Auto-retry queued after failure',
        )


def _worker_loop() -> None:
    while True:
        try:
            _reconcile_pending_attempts()
            _reconcile_failed_attempts()
            job = _claim_next_pending_job()
            if job is None:
                _WAKE_EVENT.wait(_POLL_INTERVAL_SECONDS)
                _WAKE_EVENT.clear()
                continue
            _run_local(job.attempt_id, job.id)
        except Exception:
            logger.exception('Evaluation queue worker loop error')
            time.sleep(_POLL_INTERVAL_SECONDS)


def start_local_evaluation_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True
    t = threading.Thread(target=_worker_loop, daemon=True, name='eval-queue-loop')
    t.start()


def enqueue_attempt_evaluation(attempt_id: int) -> str:
    job = EvaluationJob.objects.create(
        attempt_id=attempt_id,
        status=EvaluationJob.STATUS_PENDING,
        worker_backend=getattr(settings, 'EVALUATION_QUEUE_BACKEND', 'local').lower(),
    )

    backend = getattr(settings, 'EVALUATION_QUEUE_BACKEND', 'local').lower()
    if backend == 'celery':
        try:
            from attempts.tasks import evaluate_attempt_task

            evaluate_attempt_task.delay(attempt_id, job.id)
            return 'celery'
        except Exception:
            logger.exception('Falling back to local evaluation executor for attempt %s', attempt_id)

    _WAKE_EVENT.set()
    return 'local'


def enqueue_recalculation_for_test(test_id: int) -> bool:
    """
    Schedule recalculate_marks_for_test(test) to run in the background thread pool.

    Deduplication with pending re-run:
    - If no recalc is running: start one immediately, return True.
    - If a recalc is already running: mark as pending so a second run fires
      automatically when the current one finishes.  This guarantees that after
      a burst of evaluations (e.g. 100 simultaneous submits) at least one
      recalc runs AFTER all evaluations have completed, fixing stale ranks.

    Returns True if a new background job was submitted, False if one was already
    running (but the pending flag was set for a follow-up run).
    """
    with _RECALC_LOCK:
        if test_id in _RECALC_IN_PROGRESS:
            _RECALC_PENDING.add(test_id)
            logger.info(
                'Recalculation for test %s already running — queued a follow-up run.',
                test_id,
            )
            return False
        _RECALC_IN_PROGRESS.add(test_id)

    def _worker():
        from django.db import connection
        try:
            from testseries.models import Test
            from evaluation.services import recalculate_marks_for_test
            try:
                test = Test.objects.get(pk=test_id)
            except Test.DoesNotExist:
                logger.warning('enqueue_recalculation_for_test: Test %s not found.', test_id)
                return
            recalculate_marks_for_test(test)
            logger.info('Background recalculation completed for test %s.', test_id)
        except Exception:
            logger.exception('Background recalculate_marks_for_test failed for test %s.', test_id)
        finally:
            with _RECALC_LOCK:
                _RECALC_IN_PROGRESS.discard(test_id)
                needs_rerun = test_id in _RECALC_PENDING
                _RECALC_PENDING.discard(test_id)
            connection.close()
            # If new evaluations completed while we were running, fire one more
            # recalc now that this one is done so ranks reflect the full set.
            if needs_rerun:
                logger.info('Re-running recalculation for test %s (pending follow-up).', test_id)
                enqueue_recalculation_for_test(test_id)

    EVALUATION_EXECUTOR.submit(_worker)
    return True