from django.urls import path
from apps.settlement.views import (
    ReconciliationDetailView,
    ReconciliationListView,
    ReconciliationRunView,
    WebhookReceiverView,
)

app_name = "settlement"

urlpatterns = [
    path("webhooks/providers/<str:provider>/", WebhookReceiverView.as_view(), name="webhook_receiver"),
    path("admin/reconciliation/", ReconciliationListView.as_view(), name="reconciliation_list"),
    path("admin/reconciliation/run/", ReconciliationRunView.as_view(), name="reconciliation_run"),
    path("admin/reconciliation/<str:batch_code>/", ReconciliationDetailView.as_view(), name="reconciliation_detail"),
]
