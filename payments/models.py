from django.db import models
from django.conf import settings


class SeriesAccess(models.Model):
    """
    Grants a user access to an entire test series.
    Can be created via:
      - a successful Razorpay payment  (access_type='paid')
      - manual admin grant             (access_type='admin_granted')
    Admin can revoke at any time by setting is_active=False.
    """
    ACCESS_PAID = 'paid'
    ACCESS_ADMIN = 'admin_granted'
    ACCESS_TYPE_CHOICES = [
        (ACCESS_PAID, 'Paid'),
        (ACCESS_ADMIN, 'Admin Granted'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='series_accesses',
    )
    series = models.ForeignKey(
        'testseries.TestSeries',
        on_delete=models.CASCADE,
        related_name='user_accesses',
    )
    access_type = models.CharField(
        max_length=20, choices=ACCESS_TYPE_CHOICES, default=ACCESS_PAID
    )
    is_active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_series_accesses',
        help_text='Admin who manually granted this access (null for payments)',
    )
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    amount_paid = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Amount paid in INR at the time of purchase.',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Access expiry datetime. Null = never expires (legacy). '
                  'Paid and admin-granted access expires 3 months from grant.',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'series'],
                name='uq_series_access_user_series',
            )
        ]
        indexes = [
            models.Index(fields=['user', 'series', 'is_active']),
            models.Index(fields=['series', 'is_active']),
        ]
        ordering = ['-granted_at']

    def __str__(self):
        status = 'active' if self.is_active else 'revoked'
        return f"{self.user} — {self.series.name} ({self.access_type}, {status})"


class SeriesPlan(models.Model):
    """
    A purchasable access plan for a test series.
    Admin can define multiple plans per series with different durations and prices.
    e.g. "3 Months — ₹199", "6 Months — ₹349", "1 Year — ₹599"
    """
    series = models.ForeignKey(
        'testseries.TestSeries',
        on_delete=models.CASCADE,
        related_name='plans',
    )
    name = models.CharField(
        max_length=100,
        help_text='Display name, e.g. "3 Months", "Half Year", "1 Year"',
    )
    duration_days = models.PositiveIntegerField(
        help_text='Access duration in days (e.g. 90, 180, 365)',
    )
    price = models.DecimalField(
        max_digits=8, decimal_places=2,
        help_text='Price in INR',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price']
        unique_together = [('series', 'name')]

    def __str__(self):
        return f"{self.series.name} — {self.name} (₹{self.price}, {self.duration_days}d)"


class RazorpayOrder(models.Model):
    """
    Tracks a Razorpay payment order for series access purchase.
    One order per (user, series, plan) attempt; a new order is created only if no
    pending order exists for the same plan.
    """
    STATUS_CREATED = 'created'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='razorpay_orders',
    )
    series = models.ForeignKey(
        'testseries.TestSeries',
        on_delete=models.CASCADE,
        related_name='razorpay_orders',
    )
    plan = models.ForeignKey(
        SeriesPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text='The plan selected by the user (null for legacy single-price orders)',
    )
    razorpay_order_id = models.CharField(max_length=100, unique=True)
    amount_paise = models.PositiveIntegerField(
        help_text='Amount in paise (INR × 100).'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED
    )
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature = models.CharField(max_length=256, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'series', 'status']),
            models.Index(fields=['razorpay_order_id']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Order {self.razorpay_order_id} — {self.user} — {self.series.name}"
