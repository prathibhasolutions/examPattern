import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from testseries.models import TestSeries
from .models import RazorpayOrder, SeriesAccess, SeriesPlan
from .utils import user_has_series_access

logger = logging.getLogger(__name__)


def _razorpay_client():
    import razorpay
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


# ─── Payment page ─────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def series_payment_page(request, slug):
    """Show the Razorpay checkout page for a test series."""
    series = get_object_or_404(TestSeries, slug=slug, is_active=True)

    # Already has access — send straight to the series
    has_access, _ = user_has_series_access(request.user, series)
    if has_access:
        return redirect('tests_series_detail', slug=slug)

    plans = list(series.plans.filter(is_active=True).order_by('price'))

    # No plans and free series — skip payment
    if not plans and series.price == 0:
        return redirect('tests_series_detail', slug=slug)

    return render(request, 'payments/series_payment.html', {
        'series': series,
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'plans': plans,
        # Legacy fallback when no plans are set
        'amount': series.price,
    })


# ─── Create Razorpay order ────────────────────────────────────────────────────

@login_required
@require_POST
def create_razorpay_order(request, slug):
    """
    POST /pay/<slug>/create-order/
    Creates (or returns an existing pending) Razorpay order.
    Accepts optional plan_id; if provided, uses plan price + duration.
    Returns JSON: {order_id, amount, currency, key_id}
    """
    series = get_object_or_404(TestSeries, slug=slug, is_active=True)

    has_access, _ = user_has_series_access(request.user, series)
    if has_access:
        return JsonResponse({'error': 'You already have access to this series.'}, status=400)

    # Resolve plan (optional)
    plan = None
    plan_id = request.POST.get('plan_id', '').strip()
    if plan_id:
        try:
            plan = SeriesPlan.objects.get(pk=int(plan_id), series=series, is_active=True)
        except (SeriesPlan.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Selected plan not found.'}, status=400)
        amount_paise = int(plan.price * 100)
    else:
        # Legacy single-price fallback
        if series.price == 0:
            return JsonResponse({'error': 'This series is free.'}, status=400)
        amount_paise = int(series.price * 100)

    # Re-use any pending order for the same (user, series, plan)
    existing_qs = RazorpayOrder.objects.filter(
        user=request.user,
        series=series,
        status=RazorpayOrder.STATUS_CREATED,
    )
    existing_qs = existing_qs.filter(plan=plan)  # plan can be None
    existing = existing_qs.order_by('-created_at').first()

    if existing:
        return JsonResponse({
            'order_id': existing.razorpay_order_id,
            'amount': existing.amount_paise,
            'currency': 'INR',
            'key_id': settings.RAZORPAY_KEY_ID,
        })

    try:
        client = _razorpay_client()
        rz_order = client.order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'payment_capture': 1,
            'notes': {
                'series_slug': series.slug,
                'user_id': str(request.user.id),
                'plan_id': str(plan.id) if plan else '',
            },
        })
    except Exception as exc:
        logger.error("Razorpay order creation failed for user=%s series=%s plan=%s: %s",
                     request.user.id, series.slug, plan_id, exc)
        return JsonResponse(
            {'error': 'Payment service unavailable. Please try again later.'},
            status=503,
        )

    order = RazorpayOrder.objects.create(
        user=request.user,
        series=series,
        plan=plan,
        razorpay_order_id=rz_order['id'],
        amount_paise=amount_paise,
        status=RazorpayOrder.STATUS_CREATED,
    )

    return JsonResponse({
        'order_id': order.razorpay_order_id,
        'amount': order.amount_paise,
        'currency': 'INR',
        'key_id': settings.RAZORPAY_KEY_ID,
    })


# ─── Verify payment ───────────────────────────────────────────────────────────

@login_required
@require_POST
def verify_payment(request):
    """
    POST /pay/verify/
    Verifies Razorpay HMAC signature and grants SeriesAccess on success.
    Returns JSON: {success: true, redirect_url} or {error: ...}
    """
    razorpay_order_id = request.POST.get('razorpay_order_id', '').strip()
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    razorpay_signature = request.POST.get('razorpay_signature', '').strip()

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return JsonResponse({'error': 'Incomplete payment details received.'}, status=400)

    # Look up our stored order — must belong to this user and be in 'created' state
    try:
        order = RazorpayOrder.objects.select_related('series').get(
            razorpay_order_id=razorpay_order_id,
            user=request.user,
        )
    except RazorpayOrder.DoesNotExist:
        return JsonResponse({'error': 'Order not found.'}, status=404)

    # If already paid (e.g. webhook beat us here), just return success
    if order.status == RazorpayOrder.STATUS_PAID:
        return JsonResponse({
            'success': True,
            'redirect_url': f'/tests/series/{order.series.slug}/',
        })

    # Server-side HMAC-SHA256 signature verification
    key_secret = settings.RAZORPAY_KEY_SECRET.encode('utf-8')
    payload = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
    expected_signature = hmac.new(key_secret, payload, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, razorpay_signature):
        logger.warning(
            "Invalid Razorpay signature: order=%s user=%s",
            razorpay_order_id, request.user.id,
        )
        order.status = RazorpayOrder.STATUS_FAILED
        order.save(update_fields=['status', 'updated_at'])
        return JsonResponse({'error': 'Payment verification failed. Please contact support.'}, status=400)

    with transaction.atomic():
        # Mark order paid
        order.status = RazorpayOrder.STATUS_PAID
        order.razorpay_payment_id = razorpay_payment_id
        order.razorpay_signature = razorpay_signature
        order.save(update_fields=['status', 'razorpay_payment_id', 'razorpay_signature', 'updated_at'])

        # Grant series access (get_or_create is idempotent against duplicate calls)
        from django.utils import timezone
        duration_days = order.plan.duration_days if order.plan else 90
        expiry = timezone.now() + timedelta(days=duration_days)
        amount = order.plan.price if order.plan else order.series.price
        access, created = SeriesAccess.objects.get_or_create(
            user=request.user,
            series=order.series,
            defaults={
                'access_type': SeriesAccess.ACCESS_PAID,
                'is_active': True,
                'razorpay_payment_id': razorpay_payment_id,
                'amount_paid': amount,
                'expires_at': expiry,
            },
        )
        if not created:
            # Renew / reinstate on new payment — reset expiry from now
            access.is_active = True
            access.access_type = SeriesAccess.ACCESS_PAID
            access.razorpay_payment_id = razorpay_payment_id
            access.amount_paid = amount
            access.expires_at = expiry
            access.save(update_fields=[
                'is_active', 'access_type', 'razorpay_payment_id', 'amount_paid', 'expires_at'
            ])

    return JsonResponse({
        'success': True,
        'redirect_url': f'/tests/series/{order.series.slug}/',
    })


# ─── Razorpay webhook (server-to-server fallback) ────────────────────────────

@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    POST /pay/webhook/razorpay/
    Razorpay calls this server-to-server when payment is captured.
    Acts as a fallback if verify_payment wasn't called (e.g. browser closed).
    Configure in Razorpay Dashboard → Settings → Webhooks.
    Set the webhook secret in RAZORPAY_WEBHOOK_SECRET env var.
    """
    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    if not webhook_secret:
        # Webhook secret not configured — skip verification (not recommended for production)
        logger.warning("RAZORPAY_WEBHOOK_SECRET not set; skipping webhook signature check.")
    else:
        received_signature = request.headers.get('X-Razorpay-Signature', '')
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            request.body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, received_signature):
            logger.warning("Razorpay webhook signature mismatch")
            return HttpResponse(status=400)

    try:
        event = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    event_type = event.get('event', '')

    if event_type == 'payment.captured':
        payment = event.get('payload', {}).get('payment', {}).get('entity', {})
        rz_order_id = payment.get('order_id')
        rz_payment_id = payment.get('id')

        if rz_order_id and rz_payment_id:
            try:
                order = RazorpayOrder.objects.select_related('series').get(
                    razorpay_order_id=rz_order_id,
                )
            except RazorpayOrder.DoesNotExist:
                logger.warning("Webhook: no RazorpayOrder found for order_id=%s", rz_order_id)
                return HttpResponse(status=200)

            if order.status != RazorpayOrder.STATUS_PAID:
                with transaction.atomic():
                    order.status = RazorpayOrder.STATUS_PAID
                    order.razorpay_payment_id = rz_payment_id
                    order.save(update_fields=['status', 'razorpay_payment_id', 'updated_at'])

                    from django.utils import timezone
                    _duration = order.plan.duration_days if order.plan else 90
                    _expiry = timezone.now() + timedelta(days=_duration)
                    _amount = order.plan.price if order.plan else order.series.price
                    _access, _created = SeriesAccess.objects.get_or_create(
                        user=order.user,
                        series=order.series,
                        defaults={
                            'access_type': SeriesAccess.ACCESS_PAID,
                            'is_active': True,
                            'razorpay_payment_id': rz_payment_id,
                            'amount_paid': _amount,
                            'expires_at': _expiry,
                        },
                    )
                    if not _created:
                        _access.is_active = True
                        _access.expires_at = _expiry
                        _access.razorpay_payment_id = rz_payment_id
                        _access.save(update_fields=['is_active', 'expires_at', 'razorpay_payment_id'])
                logger.info(
                    "Webhook granted access: user=%s series=%s",
                    order.user_id, order.series.slug,
                )

    return HttpResponse(status=200)
