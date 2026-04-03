from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.db.models import Prefetch

from testseries.models import TestSeries, Test
from attempts.models import TestAttempt


def staff_required(view_func):
    """Decorator: allow only is_staff or is_superuser users."""
    @login_required
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            return HttpResponseForbidden("Access denied.")
        return view_func(request, *args, **kwargs)
    wrapped.__name__ = view_func.__name__
    return wrapped


@staff_required
def monitor_home(request):
    """Browse student attempts by test series / test."""
    series_list = (
        TestSeries.objects
        .prefetch_related(
            Prefetch('tests', queryset=Test.objects.order_by('name'))
        )
        .order_by('name')
    )

    selected_test = None
    student_rows = []

    test_id = request.GET.get('test')
    if test_id:
        selected_test = get_object_or_404(Test, id=test_id)
        student_rows = (
            TestAttempt.objects
            .filter(test=selected_test, status=TestAttempt.STATUS_SUBMITTED)
            .select_related('user', 'evaluation')
            .order_by('user__username', 'attempt_number')
        )

    return render(request, 'monitor/home.html', {
        'series_list': series_list,
        'selected_test': selected_test,
        'student_rows': student_rows,
    })
