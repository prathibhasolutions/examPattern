import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Prefetch
from django.db.models import F
from django.db import transaction, IntegrityError

from .models import TestAttempt, Answer, AttemptSectionTiming
from .serializers import TestAttemptSerializer, AnswerSerializer
from .evaluation_queue import enqueue_attempt_evaluation

logger = logging.getLogger(__name__)


def _increment_section_timing(attempt_id: int, section_id: int, delta_seconds: int) -> None:
    if delta_seconds <= 0:
        return

    updated = AttemptSectionTiming.objects.filter(
        attempt_id=attempt_id,
        section_id=section_id,
    ).update(time_spent_seconds=F('time_spent_seconds') + delta_seconds)
    if updated:
        return

    try:
        AttemptSectionTiming.objects.create(
            attempt_id=attempt_id,
            section_id=section_id,
            time_spent_seconds=delta_seconds,
        )
    except IntegrityError:
        AttemptSectionTiming.objects.filter(
            attempt_id=attempt_id,
            section_id=section_id,
        ).update(time_spent_seconds=F('time_spent_seconds') + delta_seconds)


def _materialize_section_timings_json(attempt: TestAttempt) -> dict:
    base_timings = {
        str(section_id): int(seconds)
        for section_id, seconds in (attempt.section_timings or {}).items()
    }
    rows = AttemptSectionTiming.objects.filter(attempt=attempt).values('section_id', 'time_spent_seconds')
    section_timings = dict(base_timings)
    for row in rows:
        section_key = str(row['section_id'])
        section_timings[section_key] = section_timings.get(section_key, 0) + int(row['time_spent_seconds'])
    attempt.section_timings = section_timings
    attempt.save(update_fields=['section_timings'])
    return section_timings


def _extract_final_answers(payload) -> list[dict]:
    """Normalize both legacy and compact submit payload formats.

    Legacy format:
      {"final_answers": [{"question": 1, "selected_option_ids": [...], "response_text": "", "status": "answered"}]}

    Compact format:
      {"fa": [{"q": 1, "o": [...], "t": "", "s": "answered"}]}
    """
    legacy = payload.get('final_answers')
    if isinstance(legacy, list):
        return legacy

    compact = payload.get('fa')
    if not isinstance(compact, list):
        return []

    normalized = []
    for item in compact:
        if not isinstance(item, dict):
            continue
        question_id = item.get('q') or item.get('question')
        if not question_id:
            continue
        row = {'question': question_id}
        if 'o' in item or 'selected_option_ids' in item:
            row['selected_option_ids'] = item.get('o', item.get('selected_option_ids')) or []
        if 't' in item or 'response_text' in item:
            row['response_text'] = item.get('t', item.get('response_text')) or ''
        if 's' in item or 'status' in item:
            row['status'] = item.get('s', item.get('status')) or 'visited'
        normalized.append(row)
    return normalized


class TestAttemptViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing test attempts and answers.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TestAttemptSerializer

    def get_queryset(self):
        """Return only attempts belonging to the current user."""
        from questions.models import Option
        return (
            TestAttempt.objects
            .filter(user=self.request.user)
            .select_related('test')
            .prefetch_related(
                Prefetch(
                    'answers',
                    queryset=Answer.objects.prefetch_related(
                        Prefetch('selected_options', queryset=Option.objects.only('id'))
                    ),
                )
            )
        )

    def retrieve(self, request, *args, **kwargs):
        """
        GET /api/attempts/{id}/
        Retrieve a test attempt with all its answers.
        """
        attempt = self.get_object()
        serializer = self.get_serializer(attempt)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_answer(self, request, pk=None):
        """
        Save/update an answer for a question.
        POST /api/attempts/{id}/save_answer/
        
        Body:
        {
            "question": 1,
            "selected_option_ids": [1, 2],  // for MCQ/MCA
            "response_text": "...",  // for subjective
            "status": "answered",  // not_visited, visited, answered, marked_for_review, answered_and_marked
            "time_spent_seconds": 30
        }
        """
        attempt = self.get_object()

        # Ensure attempt is in progress
        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        question_id = request.data.get('question')
        if not question_id:
            return Response(
                {"error": "question id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create answer
        answer, created = Answer.objects.get_or_create(
            attempt=attempt,
            question_id=question_id,
        )

        # Update answer fields
        if 'selected_option_ids' in request.data:
            answer.selected_options.set(request.data.get('selected_option_ids', []))

        if 'response_text' in request.data:
            answer.response_text = request.data.get('response_text', '')

        if 'status' in request.data:
            answer.status = request.data.get('status')

        # time_spent_seconds is NOT updated here — it is accumulated exclusively
        # via the track_question_time endpoint to prevent overwriting with stale values.

        answer.save()

        serializer = AnswerSerializer(answer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def submit(self, request, pk=None):
        """
        Submit a test attempt.
        POST /api/attempts/{id}/submit/

        Returns immediately after marking the attempt as submitted.
        Evaluation runs in a background thread so the HTTP worker is freed
        instantly — critical for handling simultaneous submissions without
        server memory spikes.
        """
        attempt = self.get_object()

        if attempt.status == TestAttempt.STATUS_SUBMITTED:
            serializer = self.get_serializer(attempt)
            return Response(serializer.data, status=status.HTTP_200_OK)

        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        final_answers = _extract_final_answers(request.data)
        if isinstance(final_answers, list) and final_answers:
            for item in final_answers:
                if not isinstance(item, dict):
                    continue
                question_id = item.get('question')
                if not question_id:
                    continue
                answer, _ = Answer.objects.get_or_create(
                    attempt=attempt,
                    question_id=question_id,
                )
                answer.response_text = item.get('response_text', '') or ''
                answer.status = item.get('status', answer.status) or answer.status
                answer.save(update_fields=['response_text', 'status'])
                if 'selected_option_ids' in item:
                    answer.selected_options.set(item.get('selected_option_ids') or [])

        # Compute actual active elapsed time.
        # Use the saved heartbeat timer value when available — more accurate
        # than wall-clock for tests that were paused or resumed.
        test_duration = attempt.test.duration_seconds or 0
        if attempt.time_remaining_seconds is not None and test_duration > 0:
            elapsed = test_duration - attempt.time_remaining_seconds
        else:
            elapsed = int((timezone.now() - attempt.started_at).total_seconds())

        # Commit the submission status immediately so the response is fast.
        attempt.status = TestAttempt.STATUS_SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.duration_seconds = max(0, int(elapsed))
        attempt.time_remaining_seconds = None
        attempt.evaluation_state = TestAttempt.EVAL_PENDING
        attempt.evaluation_started_at = None
        attempt.evaluation_finished_at = None
        attempt.evaluation_error = ''
        _materialize_section_timings_json(attempt)
        attempt.save()

        # Kick off evaluation in a background thread — the student is already
        # redirected to the submitted page which polls for results.
        transaction.on_commit(lambda: enqueue_attempt_evaluation(attempt.id))

        serializer = self.get_serializer(attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def evaluation_status(self, request, pk=None):
        """
        Poll for evaluation completion.
        GET /api/attempts/{id}/evaluation_status/

        The submitted page calls this every 1.5 seconds until
        evaluation_ready is true, then redirects to the results page.

        Returns:
        {
            "evaluation_ready": true | false,
            "evaluation_state": "pending|running|success|failed"
        }
        """
        attempt = self.get_object()

        # Only the attempt owner can poll (admins are allowed via get_queryset override)
        from evaluation.models import EvaluationResult
        from evaluation.models import EvaluationJob
        ready = EvaluationResult.objects.filter(attempt=attempt).exists()

        pending_jobs = EvaluationJob.objects.filter(status=EvaluationJob.STATUS_PENDING)
        queue_depth = pending_jobs.count()
        queue_position = (
            pending_jobs.filter(queued_at__lt=attempt.submitted_at).count() + 1
            if attempt.evaluation_state == TestAttempt.EVAL_PENDING and attempt.submitted_at
            else None
        )
        return Response({
            'evaluation_ready': ready,
            'evaluation_state': attempt.evaluation_state,
            'evaluation_error': attempt.evaluation_error,
            'queue_depth': queue_depth,
            'queue_position': queue_position,
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_timer(self, request, pk=None):
        """
        Save the current timer remaining seconds.
        Called periodically by the client as a heartbeat so that on resume
        the timer can restart from exactly where it stopped.
        POST /api/attempts/{id}/save_timer/
        Body: { "remaining_seconds": 1234 }
        """
        attempt = self.get_object()
        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response({'error': 'Attempt is not in progress'}, status=status.HTTP_400_BAD_REQUEST)
        remaining = request.data.get('remaining_seconds')
        if remaining is not None:
            attempt.time_remaining_seconds = max(0, int(remaining))
            attempt.save(update_fields=['time_remaining_seconds'])
        return Response({'saved': True})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def track_question_time(self, request, pk=None):
        """
        Track time spent viewing a question (accumulates if viewed multiple times).
        POST /api/attempts/{id}/track_question_time/
        
        Body:
        {
            "question": 1,
            "time_spent_seconds": 30
        }
        """
        attempt = self.get_object()
        
        # Ensure attempt is in progress
        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        question_id = request.data.get('question')
        time_spent = int(request.data.get('time_spent_seconds', 0) or 0)
        
        if not question_id:
            return Response(
                {"error": "question id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Get or create answer
        answer, created = Answer.objects.get_or_create(
            attempt=attempt,
            question_id=question_id,
        )
        
        # ACCUMULATE time (don't replace)
        answer.time_spent_seconds += time_spent
        answer.save(update_fields=['time_spent_seconds'])
        
        # Update section timings in a normalized hot table to avoid rewriting
        # the full JSON blob on every 5-second heartbeat.
        from questions.models import Question
        section_id = Question.objects.filter(id=question_id).values_list('section_id', flat=True).first()
        if section_id is not None:
            _increment_section_timing(attempt.id, int(section_id), time_spent)
        
        return Response(
            {
                "success": True,
                "question": question_id,
                "total_time_on_question": answer.time_spent_seconds,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def retry_evaluation(self, request, pk=None):
        attempt = self.get_object()
        if attempt.status != TestAttempt.STATUS_SUBMITTED:
            return Response(
                {'error': 'Attempt is not submitted'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attempt.evaluation_state in {TestAttempt.EVAL_PENDING, TestAttempt.EVAL_RUNNING}:
            return Response({'queued': True, 'evaluation_state': attempt.evaluation_state})

        attempt.evaluation_state = TestAttempt.EVAL_PENDING
        attempt.evaluation_error = ''
        attempt.evaluation_started_at = None
        attempt.evaluation_finished_at = None
        attempt.save(update_fields=['evaluation_state', 'evaluation_error', 'evaluation_started_at', 'evaluation_finished_at'])
        transaction.on_commit(lambda: enqueue_attempt_evaluation(attempt.id))
        return Response({'queued': True, 'evaluation_state': attempt.evaluation_state})

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def check_timing(self, request, pk=None):
        """
        Check remaining time for the attempt.
        GET /api/attempts/{id}/check_timing/
        
        Returns:
        {
            "elapsed_seconds": 120,
            "remaining_seconds": 480,
            "total_duration": 600,
            "time_limit_exceeded": false
        }
        """
        attempt = self.get_object()

        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {
                    "status": attempt.status,
                    "elapsed_seconds": attempt.duration_seconds,
                }
            )

        total_duration = attempt.test.duration_seconds or 0

        # Use saved timer value if available — correct for resumed tests
        # (wall-clock elapsed would include offline time between sessions)
        if attempt.time_remaining_seconds is not None:
            remaining = attempt.time_remaining_seconds
            elapsed = (total_duration - remaining) if total_duration > 0 else None
        else:
            elapsed = int((timezone.now() - attempt.started_at).total_seconds())
            remaining = max(0, total_duration - elapsed) if total_duration > 0 else None

        return Response(
            {
                "elapsed_seconds": elapsed,
                "remaining_seconds": remaining,
                "total_duration": total_duration if total_duration > 0 else None,
                "time_limit_exceeded": total_duration > 0 and remaining is not None and remaining <= 0,
            }
        )
