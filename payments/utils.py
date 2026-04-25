"""
Access control helpers for the payments/paywall system.

Call user_has_series_access(user, series) at every gate point
(test_instructions view, start_attempt API action) to decide
whether a user is allowed to attempt tests in a given series.
"""


def user_has_series_access(user, series):
    """
    Returns (has_access: bool, reason: str).

    Reasons
    -------
    'staff'           – user is staff or superuser (always allowed)
    'legacy'          – user has has_legacy_access=True
    'paid_or_admin'   – active SeriesAccess record exists
    'free_first_test' – user has never started a test in this series
    'free_series'     – series.price == 0 (no charge)
    'blocked'         – user must purchase access
    """
    from .models import SeriesAccess
    from attempts.models import TestAttempt

    # Staff / superusers bypass everything
    if user.is_staff or user.is_superuser:
        return True, 'staff'

    # Legacy users (created before the paywall)
    if user.has_legacy_access:
        return True, 'legacy'

    # Explicit access record (paid or admin-granted) — check expiry too
    from django.utils import timezone
    access = SeriesAccess.objects.filter(
        user=user, series=series, is_active=True
    ).first()
    if access:
        if access.expires_at is None or access.expires_at > timezone.now():
            return True, 'paid_or_admin'
        # Expired — auto-deactivate
        access.is_active = False
        access.save(update_fields=['is_active'])

    # Free first test — user has never started any test in this series
    has_prior_attempt = TestAttempt.objects.filter(
        user=user,
        test__series=series,
    ).exists()

    if not has_prior_attempt:
        return True, 'free_first_test'

    # Series is free (price = 0) — no payment needed
    if series.price == 0:
        return True, 'free_series'

    return False, 'blocked'
