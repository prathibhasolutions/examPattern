import logging
import threading

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Prefetch
from django.db import transaction

from .models import TestAttempt, Answer
from .serializers import TestAttemptSerializer, AnswerSerializer
from evaluation.services import evaluate_attempt

logger = logging.getLogger(__name__)


def _run_evaluation_in_background(attempt_id: int) -> None:
    """
    Spawn a background thread to evaluate an attempt after submission so the
    submit endpoint can return immediately without blocking the HTTP worker.

    The thread gets a fresh database connection because Django's connection
    objects are not safe to share across threads.
    """
    def _worker():
        from django.db import connection
        try:
            attempt = TestAttempt.objects.select_related('test', 'user').get(pk=attempt_id)
            evaluate_attempt(attempt)
        except Exception:
            logger.exception('Background evaluate_attempt failed for attempt %s', attempt_id)
        finally:
            # Always close the DB connection opened by this thread so it is
            # returned to the pool and not leaked.
            connection.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


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

        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        attempt.save()

        # Kick off evaluation in a background thread — the student is already
        # redirected to the submitted page which polls for results.
        _run_evaluation_in_background(attempt.id)

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
            "evaluation_ready": true | false
        }
        """
        attempt = self.get_object()

        # Only the attempt owner can poll (admins are allowed via get_queryset override)
        from evaluation.models import EvaluationResult
        ready = EvaluationResult.objects.filter(attempt=attempt).exists()
        return Response({'evaluation_ready': ready})

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
        time_spent = request.data.get('time_spent_seconds', 0)
        
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
        
        # Update section timings
        from questions.models import Question
        question = Question.objects.get(id=question_id)
        section_id = str(question.section.id)
        
        if section_id not in attempt.section_timings:
            attempt.section_timings[section_id] = 0
        
        attempt.section_timings[section_id] += time_spent
        attempt.save(update_fields=['section_timings'])
        
        return Response(
            {
                "success": True,
                "question": question_id,
                "total_time_on_question": answer.time_spent_seconds,
            },
            status=status.HTTP_200_OK,
        )

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
