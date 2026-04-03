from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import CustomUser
from testseries.models import TestSeries, Test


def superuser_required(view_func):
    """Decorator that requires the user to be a superuser."""
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            return render(request, 'superadmin/403.html', status=403)
        return view_func(request, *args, **kwargs)
    wrapped.__name__ = view_func.__name__
    return wrapped


@superuser_required
def dashboard(request):
    """Main superadmin dashboard with stats overview."""
    stats = {
        'total_users': CustomUser.objects.count(),
        'superusers': CustomUser.objects.filter(is_superuser=True).count(),
        'staff_users': CustomUser.objects.filter(is_staff=True, is_superuser=False).count(),
        'regular_users': CustomUser.objects.filter(is_staff=False, is_superuser=False).count(),
        'total_series': TestSeries.objects.count(),
        'active_series': TestSeries.objects.filter(is_active=True).count(),
        'total_tests': Test.objects.count(),
        'active_tests': Test.objects.filter(is_active=True).count(),
    }
    return render(request, 'superadmin/dashboard.html', {'stats': stats})


# ─── USER MANAGEMENT ─────────────────────────────────────────────────────────

@superuser_required
def user_list(request):
    users = (
        CustomUser.objects
        .order_by('-date_joined')
        .values('id', 'username', 'email', 'first_name', 'last_name',
                'is_superuser', 'is_staff', 'is_active', 'date_joined', 'uid')
    )
    return render(request, 'superadmin/users.html', {'users': users})


@superuser_required
@require_POST
def user_update_role(request, user_id):
    """Set a user's role: superuser / staff / regular."""
    target = get_object_or_404(CustomUser, pk=user_id)

    # Prevent editing yourself
    if target == request.user:
        return JsonResponse({'error': 'You cannot change your own role.'}, status=400)

    role = request.POST.get('role')
    if role == 'superuser':
        target.is_superuser = True
        target.is_staff = True
    elif role == 'staff':
        target.is_superuser = False
        target.is_staff = True
    elif role == 'regular':
        target.is_superuser = False
        target.is_staff = False
    else:
        return JsonResponse({'error': 'Invalid role.'}, status=400)

    target.save(update_fields=['is_superuser', 'is_staff'])
    return JsonResponse({'success': True, 'role': role})


@superuser_required
@require_POST
def user_toggle_active(request, user_id):
    """Enable or disable a user account."""
    target = get_object_or_404(CustomUser, pk=user_id)
    if target == request.user:
        return JsonResponse({'error': 'You cannot deactivate yourself.'}, status=400)
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'is_active': target.is_active})


@superuser_required
@require_POST
def user_delete(request, user_id):
    """Delete a user. Requires final_confirm=yes in POST body."""
    target = get_object_or_404(CustomUser, pk=user_id)
    if target == request.user:
        return JsonResponse({'error': 'You cannot delete yourself.'}, status=400)
    if request.POST.get('final_confirm') != 'yes':
        return JsonResponse({'error': 'Confirmation missing.'}, status=400)
    username = target.username
    target.delete()
    return JsonResponse({'success': True, 'deleted': username})


# ─── TEST SERIES MANAGEMENT ──────────────────────────────────────────────────

@superuser_required
def series_list(request):
    series = (
        TestSeries.objects
        .annotate(test_count=Count('tests'))
        .order_by('name')
    )
    return render(request, 'superadmin/series.html', {'series': series})


@superuser_required
@require_POST
def series_toggle_active(request, series_id):
    series = get_object_or_404(TestSeries, pk=series_id)
    series.is_active = not series.is_active
    series.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'is_active': series.is_active})


@superuser_required
@require_POST
def series_delete(request, series_id):
    if request.POST.get('final_confirm') != 'yes':
        return JsonResponse({'error': 'Confirmation missing.'}, status=400)
    series = get_object_or_404(TestSeries, pk=series_id)
    name = series.name
    series.delete()
    return JsonResponse({'success': True, 'deleted': name})


# ─── TEST MANAGEMENT ─────────────────────────────────────────────────────────

@superuser_required
def test_list(request):
    series_qs = (
        TestSeries.objects
        .prefetch_related(
            'tests'
        )
        .annotate(test_count=Count('tests'))
        .order_by('name')
    )
    return render(request, 'superadmin/tests.html', {'series_qs': series_qs})


@superuser_required
@require_POST
def test_toggle_active(request, test_id):
    test = get_object_or_404(Test, pk=test_id)
    test.is_active = not test.is_active
    test.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'is_active': test.is_active})


@superuser_required
@require_POST
def test_delete(request, test_id):
    if request.POST.get('final_confirm') != 'yes':
        return JsonResponse({'error': 'Confirmation missing.'}, status=400)
    test = get_object_or_404(Test, pk=test_id)
    name = test.name
    test.delete()
    return JsonResponse({'success': True, 'deleted': name})
