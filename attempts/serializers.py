from rest_framework import serializers
from django.utils import timezone

from .models import TestAttempt, Answer
from questions.models import Option


class AnswerSerializer(serializers.ModelSerializer):
    selected_option_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source='selected_options',
        queryset=Option.objects.all()
    )

    class Meta:
        model = Answer
        fields = [
            'id',
            'question',
            'selected_option_ids',
            'response_text',
            'status',
            'time_spent_seconds',
            'marks_obtained',
        ]
        read_only_fields = ['marks_obtained']


class TestAttemptSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, read_only=True)
    elapsed_seconds = serializers.SerializerMethodField()

    class Meta:
        model = TestAttempt
        fields = [
            'id',
            'test',
            'attempt_number',
            'status',
            'evaluation_state',
            'evaluation_started_at',
            'evaluation_finished_at',
            'started_at',
            'submitted_at',
            'duration_seconds',
            'section_timings',
            'time_remaining_seconds',
            'score',
            'evaluation_error',
            'elapsed_seconds',
            'question_order',
            'option_order',
            'answers',
        ]
        read_only_fields = [
            'started_at',
            'submitted_at',
            'score',
            'evaluation_state',
            'evaluation_started_at',
            'evaluation_finished_at',
            'evaluation_error',
        ]

    def get_elapsed_seconds(self, obj):
        """Calculate elapsed time in seconds if attempt is in progress."""
        if obj.status == TestAttempt.STATUS_IN_PROGRESS:
            return int((timezone.now() - obj.started_at).total_seconds())
        return obj.duration_seconds
