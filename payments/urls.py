from django.urls import path
from . import views

urlpatterns = [
    path('<slug:slug>/', views.series_payment_page, name='series_payment'),
    path('<slug:slug>/create-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('verify/', views.verify_payment, name='verify_payment'),
    path('webhook/razorpay/', views.razorpay_webhook, name='razorpay_webhook'),
]
