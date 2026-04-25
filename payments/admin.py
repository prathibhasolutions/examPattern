from django.contrib import admin
from .models import SeriesAccess, RazorpayOrder


@admin.register(SeriesAccess)
class SeriesAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'series', 'access_type', 'is_active', 'amount_paid', 'granted_at')
    list_filter = ('access_type', 'is_active', 'series')
    search_fields = ('user__username', 'user__email', 'series__name')
    raw_id_fields = ('user', 'granted_by')
    readonly_fields = ('granted_at', 'razorpay_payment_id', 'amount_paid')


@admin.register(RazorpayOrder)
class RazorpayOrderAdmin(admin.ModelAdmin):
    list_display = ('razorpay_order_id', 'user', 'series', 'amount_paise', 'status', 'created_at')
    list_filter = ('status', 'series')
    search_fields = ('user__username', 'user__email', 'razorpay_order_id', 'razorpay_payment_id')
    readonly_fields = ('razorpay_order_id', 'amount_paise', 'razorpay_payment_id',
                       'razorpay_signature', 'created_at', 'updated_at')
