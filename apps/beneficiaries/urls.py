from django.urls import path
from apps.beneficiaries.views import BeneficiaryDetailView, BeneficiaryListCreateView

app_name = "beneficiaries"

urlpatterns = [
    path("", BeneficiaryListCreateView.as_view(), name="beneficiary_list_create"),
    path("<uuid:pk>/", BeneficiaryDetailView.as_view(), name="beneficiary_detail"),
]
