from django.urls import path
from apps.transactions.views import (
    AdminFeeRulesListView,
    AdminLimitsListView,
    AdminTransactionListView,
    AdminTransactionReversalView,
    TransactionDetailView,
    TransactionListView,
)

app_name = "transactions"

urlpatterns = [
    # User endpoints
    path("", TransactionListView.as_view(), name="transaction_list"),
    path("<str:transaction_code>/", TransactionDetailView.as_view(), name="transaction_detail"),

    # Admin endpoints
    path("admin/transactions/", AdminTransactionListView.as_view(), name="admin_transaction_list"),
    path("admin/transactions/<uuid:pk>/reverse/", AdminTransactionReversalView.as_view(), name="admin_transaction_reverse"),
    path("admin/limits/", AdminLimitsListView.as_view(), name="admin_limits"),
    path("admin/fees/", AdminFeeRulesListView.as_view(), name="admin_fees"),
]
