from django.core.management.base import BaseCommand

from attempts.models import TestAttempt
from attempts.evaluation_runner import process_attempt_evaluation


class Command(BaseCommand):
    help = 'Retry evaluation for submitted attempts stuck in pending/failed state.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Maximum attempts to process (default: 100)',
        )

    def handle(self, *args, **options):
        limit = max(1, int(options['limit']))
        qs = (
            TestAttempt.objects
            .filter(
                status=TestAttempt.STATUS_SUBMITTED,
                evaluation_state__in=[TestAttempt.EVAL_PENDING, TestAttempt.EVAL_FAILED],
            )
            .select_related('test', 'user')
            .order_by('submitted_at')[:limit]
        )

        attempts = list(qs)
        self.stdout.write(f'Found {len(attempts)} submitted pending/failed attempts to retry')

        success = 0
        failed = 0
        for attempt in attempts:
            try:
                process_attempt_evaluation(attempt.id)
                success += 1
            except Exception:
                failed += 1

        self.stdout.write(self.style.SUCCESS(f'Retry done. success={success}, failed={failed}'))
