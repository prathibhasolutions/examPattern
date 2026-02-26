from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Prefetch, Q

from .models import Test, TestSeries, SeriesSection, SeriesSubsection
from .serializers import TestDetailSerializer, TestListSerializer, TestSeriesSerializer


class TestSeriesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TestSeries.objects.filter(is_active=True)
    serializer_class = TestSeriesSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'


class TestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Test.objects.filter(is_active=True)
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TestDetailSerializer
        return TestListSerializer

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def attempt_count(self, request, pk=None):
        """
        Get attempt count for current user on a test.
        GET /api/tests/{id}/attempt_count/
        """
        test = self.get_object()
        from attempts.models import TestAttempt
        
        user = request.user
        attempt_count = TestAttempt.objects.filter(user=user, test=test).count()
        
        return Response({
            'attempt_count': attempt_count,
            'max_attempts': 2,
            'can_attempt': attempt_count < 2
        })

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def past_attempts(self, request, pk=None):
        """
        View past attempts and analysis for a test.
        GET /api/tests/{id}/past_attempts/
        """
        test = self.get_object()
        from attempts.models import TestAttempt
        
        user = request.user
        attempts = TestAttempt.objects.filter(user=user, test=test).order_by('attempt_number')
        
        # Serialize attempts with detailed information
        attempts_data = []
        for attempt in attempts:
            attempt_info = {
                'id': attempt.id,
                'attempt_number': attempt.attempt_number,
                'score': attempt.score,
                'started_at': attempt.started_at,
                'submitted_at': attempt.submitted_at,
                'status': attempt.status,
                'duration_seconds': attempt.duration_seconds,
            }
            attempts_data.append(attempt_info)
        
        return Response(attempts_data)

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def start_attempt(self, request, pk=None):
        """
        Start a new test attempt.
        POST /api/tests/{id}/start_attempt/
        Returns: TestAttempt with initialized answers
        Requires authentication.
        """
        test = self.get_object()
        
        # For demo: allow if logged in, otherwise use a demo user
        if request.user.is_authenticated:
            user = request.user
        else:
            # For demo purposes - in production, redirect to login
            from django.contrib.auth.models import User
            # Create or get a demo user
            user, _ = User.objects.get_or_create(
                username='demo_user',
                defaults={'email': 'demo@example.com'}
            )

        # Import here to avoid circular imports
        from attempts.models import TestAttempt, Answer
        from questions.models import Question
        from attempts.serializers import TestAttemptSerializer

        # Check attempt limit (max 2 attempts per test)
        existing_attempts = TestAttempt.objects.filter(user=user, test=test).count()
        if existing_attempts >= 2:
            return Response(
                {'error': 'Maximum attempt limit reached. You can only attempt this test twice.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create a new attempt
        attempt_number = existing_attempts + 1
        is_reattempt = attempt_number > 1

        attempt = TestAttempt.objects.create(
            user=user,
            test=test,
            attempt_number=attempt_number,
            status=TestAttempt.STATUS_IN_PROGRESS,
        )

        # Create Answer records for all questions in the test
        questions = Question.objects.filter(
            section__test=test, section__is_active=True
        ).select_related('section')

        answers = [
            Answer(
                attempt=attempt,
                question=question,
                status=Answer.STATUS_NOT_VISITED,
            )
            for question in questions
        ]
        Answer.objects.bulk_create(answers)

        # Return attempt details with all answers
        serializer = TestAttemptSerializer(attempt)
        response_data = serializer.data
        response_data['is_reattempt'] = is_reattempt
        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def user_attempts(self, request, pk=None):
        """
        Get all attempts by the current user for this test.
        GET /api/tests/{id}/user_attempts/
        """
        from attempts.models import TestAttempt
        from attempts.serializers import TestAttemptSerializer

        test = self.get_object()
        attempts = TestAttempt.objects.filter(
            test=test, user=request.user
        ).order_by('-started_at')

        serializer = TestAttemptSerializer(attempts, many=True)
        return Response(serializer.data)


# Template Views for Hierarchical Navigation
def series_list_view(request):
    """Display all test series as cards with info"""
    series = TestSeries.objects.filter(is_active=True).annotate(
        test_count=Count('tests', filter=Q(tests__is_active=True)),
        section_count=Count('sections', filter=Q(sections__is_active=True))
    )
    return render(request, 'testseries/series_list.html', {'series': series})


def series_detail_view(request, slug):
    """Display series details with sections"""
    series = get_object_or_404(
        TestSeries.objects.filter(is_active=True),
        slug=slug
    )
    sections = series.sections.filter(is_active=True).prefetch_related(
        Prefetch('subsections', queryset=SeriesSubsection.objects.filter(is_active=True).prefetch_related(
            Prefetch('tests', queryset=Test.objects.filter(is_active=True).annotate(
                question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
            ).order_by('name'))
        ))
    ).annotate(
        test_count=Count('tests', filter=Q(tests__is_active=True))
    )
    
    # Get all tests for "All Tests" tab (sorted alphabetically)
    all_tests = Test.objects.filter(
        series=series,
        is_active=True
    ).annotate(
        question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
    ).order_by('name')
    
    # Organize sectional tests by section
    sectional_data = []
    for section in sections:
        # Get tests with subsections
        subsections = section.subsections.filter(is_active=True).prefetch_related(
            Prefetch('tests', queryset=Test.objects.filter(is_active=True).annotate(
                question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
            ).order_by('name'))
        )
        
        # Get tests without subsection
        tests_without_subsection = Test.objects.filter(
            series=series,
            series_section=section,
            series_subsection__isnull=True,
            is_active=True
        ).annotate(
            question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
        ).order_by('name')
        
        sectional_data.append({
            'section': section,
            'subsections': subsections,
            'tests_without_subsection': tests_without_subsection
        })
    
    return render(request, 'testseries/series_detail.html', {
        'series': series,
        'sections': sections,
        'all_tests': all_tests,
        'sectional_data': sectional_data
    })


def section_tests_view(request, series_slug, section_slug):
    """Display all tests in a section grouped by subsections"""
    series = get_object_or_404(
        TestSeries.objects.filter(is_active=True),
        slug=series_slug
    )
    section = get_object_or_404(
        SeriesSection.objects.filter(is_active=True),
        series=series,
        slug=section_slug
    )
    
    # Get subsections with their tests
    subsections = section.subsections.filter(is_active=True).prefetch_related(
        Prefetch('tests', queryset=Test.objects.filter(is_active=True).annotate(
            question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
        ))
    )
    
    # Get tests not in any subsection
    tests_without_subsection = Test.objects.filter(
        series=series,
        series_section=section,
        series_subsection__isnull=True,
        is_active=True
    ).annotate(
        question_count=Count('sections__questions', filter=Q(sections__questions__is_active=True))
    )
    
    return render(request, 'testseries/section_tests.html', {
        'series': series,
        'section': section,
        'subsections': subsections,
        'tests_without_subsection': tests_without_subsection
    })
