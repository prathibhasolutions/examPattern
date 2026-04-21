from rest_framework import serializers

from .models import TestSeries, Test, Section
from questions.serializers import QuestionSerializer


class TestSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestSeries
        fields = ['id', 'name', 'slug', 'description', 'is_active']


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = [
            'id',
            'name',
            'order',
            'time_limit_seconds',
            'marks_per_question',
            'negative_marks_per_question',
            'is_active',
        ]


class TestDetailSerializer(serializers.ModelSerializer):
    class SectionDetailSerializer(SectionSerializer):
        questions = QuestionSerializer(many=True, read_only=True)

        class Meta(SectionSerializer.Meta):
            fields = SectionSerializer.Meta.fields + ['questions']

    sections = SectionDetailSerializer(many=True, read_only=True)

    series_name = serializers.CharField(source='series.name', read_only=True)
    series_section_name = serializers.CharField(source='series_section.name', read_only=True)
    series_subsection_name = serializers.CharField(source='series_subsection.name', read_only=True)

    class Meta:
        model = Test
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'duration_seconds',
            'use_sectional_timing',
            'marks_per_question',
            'negative_marks_per_question',
            'is_active',
            'starts_at',
            'ends_at',
            'series_name',
            'series_section_name',
            'series_subsection_name',
            'shuffle_questions',
            'continuous_numbering',
            'sections',
        ]


class TestListSerializer(serializers.ModelSerializer):
    series_name = serializers.CharField(source='series.name', read_only=True)
    series_section_name = serializers.CharField(source='series_section.name', read_only=True)
    series_subsection_name = serializers.CharField(source='series_subsection.name', read_only=True)

    class Meta:
        model = Test
        fields = [
            'id',
            'name',
            'slug',
            'series_name',
            'series_section_name',
            'series_subsection_name',
            'duration_seconds',
            'is_active',
        ]
