from django.urls import path
from apps.wallets.views import (
    AdminSystemAccountListView,
    AdminWalletListView,
    CreateKhrWalletView,
    UserWalletsListView,
    WalletBalanceView,
    WalletDetailView,
    WalletExchangeView,
    WalletLedgerView,
)

app_name = "wallets"

urlpatterns = [
    path("", WalletDetailView.as_view(), name="wallet_detail"),
    path("all/", UserWalletsListView.as_view(), name="user_wallets_all"),
    path("create-khr/", CreateKhrWalletView.as_view(), name="wallet_create_khr"),
    path("exchange/", WalletExchangeView.as_view(), name="wallet_exchange"),
    path("balance/", WalletBalanceView.as_view(), name="wallet_balance"),
    path("ledger/", WalletLedgerView.as_view(), name="wallet_ledger"),
    path("admin/wallets/", AdminWalletListView.as_view(), name="admin_wallets"),
    path("admin/system-accounts/", AdminSystemAccountListView.as_view(), name="admin_system_accounts"),
]
