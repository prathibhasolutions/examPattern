from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import CustomUser, ForgotPasswordRequest
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
    pending_pw_requests = ForgotPasswordRequest.objects.filter(status='pending').count()
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
    return render(request, 'superadmin/dashboard.html', {
        'stats': stats,
        'pending_pw_requests': pending_pw_requests,
    })


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


# ─── PASSWORD RESET REQUESTS ─────────────────────────────────────────────────

@superuser_required
def password_requests(request):
    """List all forgot-password requests, pending first."""
    pending = ForgotPasswordRequest.objects.filter(status='pending').select_related('user')
    resolved = ForgotPasswordRequest.objects.filter(status='resolved').select_related('user', 'resolved_by')[:50]
    return render(request, 'superadmin/password_requests.html', {
        'pending': pending,
        'resolved': resolved,
    })


@superuser_required
@require_POST
def resolve_password_request(request, req_id):
    """Set a new password for the user and mark the request resolved."""
    pw_request = get_object_or_404(ForgotPasswordRequest, pk=req_id, status='pending')
    new_password = request.POST.get('new_password', '').strip()
    if len(new_password) < 6:
        return JsonResponse({'error': 'Password must be at least 6 characters.'}, status=400)
    pw_request.user.set_password(new_password)
    pw_request.user.save()
    pw_request.status = 'resolved'
    pw_request.resolved_at = timezone.now()
    pw_request.resolved_by = request.user
    pw_request.save()
    return JsonResponse({'success': True, 'username': pw_request.user.username})


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
    try:
        series.delete()
    except Exception as exc:
        return JsonResponse({'error': f'Delete failed: {exc}'}, status=500)
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


# ─── SERIES PRICING ──────────────────────────────────────────────────────────

@superuser_required
def series_pricing(request):
    """List all test series with their current price; allow inline editing."""
    series_qs = TestSeries.objects.order_by('name').annotate(
        access_count=Count('user_accesses', filter=Q(user_accesses__is_active=True))
    )
    return render(request, 'superadmin/series_pricing.html', {'series_qs': series_qs})


@superuser_required
@require_POST
def series_set_price(request, series_id):
    """AJAX: update the price of a test series."""
    series = get_object_or_404(TestSeries, pk=series_id)
    try:
        price = float(request.POST.get('price', '').strip())
        if price < 0:
            return JsonResponse({'error': 'Price cannot be negative.'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid price value.'}, status=400)

    from decimal import Decimal
    series.price = Decimal(str(price))
    series.save(update_fields=['price'])
    return JsonResponse({'success': True, 'price': str(series.price)})


# ─── SERIES ACCESS MANAGEMENT ────────────────────────────────────────────────

@superuser_required
def series_access(request):
    """
    View and manage per-user series access.
    Supports filtering by user (UID/email/username) or series.
    """
    from payments.models import SeriesAccess

    filter_user_q = request.GET.get('user', '').strip()
    filter_series_id = request.GET.get('series', '').strip()

    accesses = SeriesAccess.objects.select_related('user', 'series', 'granted_by').order_by('-granted_at')

    if filter_user_q:
        accesses = accesses.filter(
            Q(user__username__icontains=filter_user_q) |
            Q(user__email__icontains=filter_user_q) |
            Q(user__uid__icontains=filter_user_q)
        )
    if filter_series_id:
        accesses = accesses.filter(series_id=filter_series_id)

    all_series = TestSeries.objects.order_by('name')

    return render(request, 'superadmin/series_access.html', {
        'accesses': accesses[:200],
        'all_series': all_series,
        'filter_user_q': filter_user_q,
        'filter_series_id': filter_series_id,
    })


@superuser_required
@require_POST
def series_access_grant(request):
    """
    AJAX: manually grant a user access to a series.
    POST body: user_id, series_id
    """
    from payments.models import SeriesAccess
    from django.utils import timezone
    from datetime import timedelta

    user_id = request.POST.get('user_id', '').strip()
    series_id = request.POST.get('series_id', '').strip()
    duration_days_raw = request.POST.get('duration_days', '').strip()

    if not user_id or not series_id:
        return JsonResponse({'error': 'user_id and series_id are required.'}, status=400)

    # Duration: default 90 days if not provided
    try:
        duration_days = int(duration_days_raw) if duration_days_raw else 90
        if duration_days < 1:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'error': 'duration_days must be a positive integer.'}, status=400)

    user = get_object_or_404(CustomUser, pk=user_id)
    series = get_object_or_404(TestSeries, pk=series_id)
    expiry = timezone.now() + timedelta(days=duration_days)

    access, created = SeriesAccess.objects.get_or_create(
        user=user,
        series=series,
        defaults={
            'access_type': SeriesAccess.ACCESS_ADMIN,
            'is_active': True,
            'granted_by': request.user,
            'expires_at': expiry,
        },
    )
    if not created:
        # Re-activate / renew expiry
        access.is_active = True
        access.access_type = SeriesAccess.ACCESS_ADMIN
        access.granted_by = request.user
        access.expires_at = expiry
        access.save(update_fields=['is_active', 'access_type', 'granted_by', 'expires_at'])

    return JsonResponse({
        'success': True,
        'access_id': access.id,
        'created': created,
    })


@superuser_required
@require_POST
def series_access_revoke(request, access_id):
    """AJAX: revoke (deactivate) a series access record."""
    from payments.models import SeriesAccess

    access = get_object_or_404(SeriesAccess, pk=access_id)
    access.is_active = False
    access.save(update_fields=['is_active'])
    return JsonResponse({'success': True})


@superuser_required
@require_POST
def series_access_toggle_legacy(request, user_id):
    """AJAX: toggle has_legacy_access for a user."""
    target = get_object_or_404(CustomUser, pk=user_id)
    target.has_legacy_access = not target.has_legacy_access
    target.save(update_fields=['has_legacy_access'])
    return JsonResponse({'success': True, 'has_legacy_access': target.has_legacy_access})


# ─── SERIES PLANS (flexible pricing) ─────────────────────────────────────────

@superuser_required
def series_plans(request, series_id):
    """List all plans for a series."""
    from payments.models import SeriesPlan
    series = get_object_or_404(TestSeries, pk=series_id)
    plans = SeriesPlan.objects.filter(series=series).order_by('price')
    return render(request, 'superadmin/series_plans.html', {
        'series': series,
        'plans': plans,
    })


@superuser_required
@require_POST
def series_plan_add(request, series_id):
    """AJAX: add a new plan to a series."""
    from payments.models import SeriesPlan
    from decimal import Decimal, InvalidOperation

    series = get_object_or_404(TestSeries, pk=series_id)
    name = request.POST.get('name', '').strip()
    duration_days = request.POST.get('duration_days', '').strip()
    price = request.POST.get('price', '').strip()

    if not name:
        return JsonResponse({'error': 'Plan name is required.'}, status=400)
    try:
        duration_days = int(duration_days)
        if duration_days < 1:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Duration must be a positive integer (days).'}, status=400)
    try:
        price = Decimal(price)
        if price < 0:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        return JsonResponse({'error': 'Price must be a non-negative number.'}, status=400)

    if SeriesPlan.objects.filter(series=series, name=name).exists():
        return JsonResponse({'error': f'A plan named "{name}" already exists for this series.'}, status=400)

    plan = SeriesPlan.objects.create(
        series=series,
        name=name,
        duration_days=duration_days,
        price=price,
        is_active=True,
    )
    return JsonResponse({
        'success': True,
        'plan': {
            'id': plan.id,
            'name': plan.name,
            'duration_days': plan.duration_days,
            'price': str(plan.price),
            'is_active': plan.is_active,
        },
    })


@superuser_required
@require_POST
def series_plan_toggle(request, plan_id):
    """AJAX: toggle a plan's is_active flag."""
    from payments.models import SeriesPlan
    plan = get_object_or_404(SeriesPlan, pk=plan_id)
    plan.is_active = not plan.is_active
    plan.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'is_active': plan.is_active})


@superuser_required
@require_POST
def series_plan_delete(request, plan_id):
    """AJAX: delete a plan."""
    from payments.models import SeriesPlan
    plan = get_object_or_404(SeriesPlan, pk=plan_id)
    plan.delete()
    return JsonResponse({'success': True})


