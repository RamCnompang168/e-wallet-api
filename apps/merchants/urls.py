from django.urls import path
from apps.merchants.views import (
    DisputeDetailView,
    DisputeListCreateView,
    DisputeResolveView,
    MerchantDetailView,
    MerchantListCreateView,
    MerchantPaymentDetailView,
    MerchantPaymentListCreateView,
    RefundDetailView,
    RefundListCreateView,
)

app_name = "merchants"

urlpatterns = [
    # Merchants
    path("merchants/", MerchantListCreateView.as_view(), name="merchant_list_create"),
    path("merchants/<str:code>/", MerchantDetailView.as_view(), name="merchant_detail"),

    # Merchant Payments
    path("merchant-payments/", MerchantPaymentListCreateView.as_view(), name="merchant_payment_list_create"),
    path("merchant-payments/<uuid:pk>/", MerchantPaymentDetailView.as_view(), name="merchant_payment_detail"),

    # Refunds
    path("refunds/", RefundListCreateView.as_view(), name="refund_list_create"),
    path("refunds/<uuid:pk>/", RefundDetailView.as_view(), name="refund_detail"),

    # Disputes
    path("disputes/", DisputeListCreateView.as_view(), name="dispute_list_create"),
    path("disputes/<uuid:pk>/", DisputeDetailView.as_view(), name="dispute_detail"),
    path("disputes/<uuid:pk>/resolve/", DisputeResolveView.as_view(), name="dispute_resolve"),
]
