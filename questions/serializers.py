from rest_framework import serializers

from .models import Question, Option


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'text', 'image', 'is_math', 'order']
        # Note: is_correct is hidden from users during test-taking


class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)
    section = serializers.IntegerField(source='section_id', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id',
            'section',
            'text',
            'image',
            'extracted_text',
            'is_math',
            'explanation',
            'marks_override',
            'negative_marks_override',
            'options',
        ]
