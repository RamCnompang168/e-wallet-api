from django.urls import path
from .views import (
    DashboardOverviewView,
    DashboardApprovalsView,
    DashboardApproveUserView,
    DashboardRejectUserView,
    DashboardUsersView,
    DashboardUserDetailView,
    DashboardWalletsView,
    DashboardTransactionsView,
    DashboardGovernmentServicesView,
    DashboardApiDocsView,
    DashboardApiTestRunnerView,
)

app_name = "dashboard"

urlpatterns = [
    path("", DashboardOverviewView.as_view(), name="overview"),
    path("approvals/", DashboardApprovalsView.as_view(), name="approvals"),
    path("approvals/<uuid:pk>/approve/", DashboardApproveUserView.as_view(), name="approve_user"),
    path("approvals/<uuid:pk>/reject/", DashboardRejectUserView.as_view(), name="reject_user"),
    path("users/", DashboardUsersView.as_view(), name="users"),
    path("users/<uuid:pk>/", DashboardUserDetailView.as_view(), name="user_detail"),
    path("wallets/", DashboardWalletsView.as_view(), name="wallets"),
    path("transactions/", DashboardTransactionsView.as_view(), name="transactions"),
    path("government/", DashboardGovernmentServicesView.as_view(), name="government"),
    path("api-docs/", DashboardApiDocsView.as_view(), name="api_docs"),
    path("api-docs/test-runner/", DashboardApiTestRunnerView.as_view(), name="api_test_runner"),
]
