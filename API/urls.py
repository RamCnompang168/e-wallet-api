from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.payments.views import (
    TopUpDetailView,
    TopUpListCreateView,
    WithdrawalDetailView,
    WithdrawalListCreateView,
    KhqrWebhookView,
)

# API Version 1 URL Registry
api_v1_patterns = [
    # 1. Authentication & Security
    path("auth/", include("apps.authentication.urls", namespace="authentication")),

    # 2. Users & Profiles
    path("users/", include("apps.users.urls", namespace="users")),

    # 3. Wallets & Double-Entry Ledger
    path("wallet/", include("apps.wallets.urls", namespace="wallets")),

    # 4. Peer-to-Peer Transfers
    path("transfers/", include("apps.transfers.urls", namespace="transfers")),

    # 5. Beneficiaries
    path("beneficiaries/", include("apps.beneficiaries.urls", namespace="beneficiaries")),

    # 6. Payments, Top-ups & Withdrawals
    path("payments/", include("apps.payments.urls", namespace="payments")),
    path("topups/", TopUpListCreateView.as_view(), name="topups_root_list_create"),
    path("topups/<uuid:pk>/", TopUpDetailView.as_view(), name="topups_root_detail"),
    path("withdrawals/", WithdrawalListCreateView.as_view(), name="withdrawals_root_list_create"),
    path("withdrawals/<uuid:pk>/", WithdrawalDetailView.as_view(), name="withdrawals_root_detail"),

    # 7. Merchants, Payments, Refunds, Disputes
    path("", include("apps.merchants.urls", namespace="merchants")),

    # 8. KYC Compliance & Identity Verification
    path("kyc/", include("apps.kyc.urls", namespace="kyc")),

    # 9. Notifications
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),

    # 10. Financial Transactions
    path("transactions/", include("apps.transactions.urls", namespace="transactions")),

    # 11. Settlement, Inbound Webhooks & Reconciliation
    path("", include("apps.settlement.urls", namespace="settlement")),
]

urlpatterns = [
    # Django Admin Site
    path("admin/", admin.site.urls),

    # OpenAPI Schema & Interactive Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # API Version 1
    path("api/v1/", include(api_v1_patterns)),

    # Direct KHQR Webhook Endpoint
    path("api/khqr/webhook/", KhqrWebhookView.as_view(), name="khqr_direct_webhook"),

    # NovaPay Web Management Dashboard Portal
    path("", include("apps.dashboard.urls", namespace="dashboard")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
