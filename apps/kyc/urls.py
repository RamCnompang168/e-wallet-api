from django.urls import path
from apps.kyc.views import (
    AdminKYCQueueView,
    AdminKYCReviewView,
    KYCListCreateView,
    KYCStatusView,
)

app_name = "kyc"

urlpatterns = [
    path("", KYCListCreateView.as_view(), name="kyc_list_create"),
    path("status/", KYCStatusView.as_view(), name="kyc_status"),
]
