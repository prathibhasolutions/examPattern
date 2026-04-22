try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

from attempts.evaluation_runner import process_attempt_evaluation


@shared_task(ignore_result=True)
def evaluate_attempt_task(attempt_id: int, job_id: int | None = None) -> None:
    process_attempt_evaluation(attempt_id, job_id=job_id)
