from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from .models import TestAttempt, Answer
from .serializers import TestAttemptSerializer, AnswerSerializer
from evaluation.services import evaluate_attempt


class TestAttemptViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing test attempts and answers.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TestAttemptSerializer

    def get_queryset(self):
        """Return only attempts belonging to the current user."""
        return TestAttempt.objects.filter(user=self.request.user)

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

        if 'time_spent_seconds' in request.data:
            answer.time_spent_seconds = request.data.get('time_spent_seconds', 0)

        answer.save()

        serializer = AnswerSerializer(answer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def submit(self, request, pk=None):
        """
        Submit a test attempt.
        POST /api/attempts/{id}/submit/
        """
        attempt = self.get_object()

        if attempt.status != TestAttempt.STATUS_IN_PROGRESS:
            return Response(
                {"error": "Attempt is not in progress"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate timing
        elapsed = (timezone.now() - attempt.started_at).total_seconds()
        test_duration = attempt.test.duration_seconds
        
        if test_duration > 0 and elapsed > test_duration:
            return Response(
                {"warning": "Time limit exceeded", "elapsed": elapsed},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark as submitted
        attempt.status = TestAttempt.STATUS_SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.duration_seconds = int(elapsed)
        attempt.save()

        evaluation = evaluate_attempt(attempt)

        serializer = self.get_serializer(attempt)
        return Response(
            {
                **serializer.data,
                'evaluation': {
                    'total_score': str(evaluation.total_score),
                    'section_scores': evaluation.section_scores,
                    'rank': evaluation.rank,
                    'percentile': str(evaluation.percentile) if evaluation.percentile is not None else None,
                },
            },
            status=status.HTTP_200_OK,
        )

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

        elapsed = int((timezone.now() - attempt.started_at).total_seconds())
        total_duration = attempt.test.duration_seconds or 0
        remaining = max(0, total_duration - elapsed) if total_duration > 0 else None

        return Response(
            {
                "elapsed_seconds": elapsed,
                "remaining_seconds": remaining,
                "total_duration": total_duration if total_duration > 0 else None,
                "time_limit_exceeded": total_duration > 0 and elapsed > total_duration,
            }
        )
