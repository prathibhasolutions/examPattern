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

        The attempt is marked as submitted in a single atomic UPDATE before
        any answer processing — so the student's submission is permanently
        saved even if the connection drops mid-request. Section timings are
        materialized inside the background evaluation runner to keep this
        response fast.
        """
        attempt = self.get_object()

        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Compute elapsed time before any DB writes.
        test_duration = attempt.test.duration_seconds or 0
        if attempt.time_remaining_seconds is not None and test_duration > 0:
            elapsed = test_duration - attempt.time_remaining_seconds
        else:
            elapsed = int((timezone.now() - attempt.started_at).total_seconds())

        # STEP 1 — Atomic UPDATE to mark submitted FIRST.
        # This single query runs before answer processing so the attempt is
        # permanently saved even if the server is killed mid-request.
        now = timezone.now()
        updated = TestAttempt.objects.filter(
            pk=attempt.pk, status=TestAttempt.STATUS_IN_PROGRESS
        ).update(
            status=TestAttempt.STATUS_SUBMITTED,
            submitted_at=now,
            duration_seconds=max(0, int(elapsed)),
            time_remaining_seconds=None,
            evaluation_state=TestAttempt.EVAL_PENDING,
            evaluation_started_at=None,
            evaluation_finished_at=None,
            evaluation_error='',
        )
        if not updated:
            # Race condition — another request already submitted this attempt.
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update in-memory object to match DB state (avoids extra refresh query).
        attempt.status = TestAttempt.STATUS_SUBMITTED
        attempt.submitted_at = now
        attempt.duration_seconds = max(0, int(elapsed))
        attempt.time_remaining_seconds = None
        attempt.evaluation_state = TestAttempt.EVAL_PENDING
        attempt.evaluation_started_at = None
        attempt.evaluation_finished_at = None
        attempt.evaluation_error = ''

        # STEP 2 — Save any final answers sent with the submit request.
        # Autosave handles most answers during the test; this is a safety net.
        final_answers = request.data.get('final_answers') or []
        if isinstance(final_answers, list) and final_answers:
            answer_updates = []
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
                answer_updates.append(answer)
                if 'selected_option_ids' in item:
                    answer.selected_options.set(item.get('selected_option_ids') or [])
            if answer_updates:
                Answer.objects.bulk_update(answer_updates, ['response_text', 'status'])

        # STEP 3 — Kick off background evaluation.
        # Section timings are materialized inside the evaluation runner.
        attempt_id = attempt.pk
        transaction.on_commit(lambda: enqueue_attempt_evaluation(attempt_id))

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
        from evaluation.models import EvaluationResult
        ready = EvaluationResult.objects.filter(attempt=attempt).exists()
        return Response({
            'evaluation_ready': ready,
            'evaluation_state': attempt.evaluation_state,
            'evaluation_error': attempt.evaluation_error,
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
