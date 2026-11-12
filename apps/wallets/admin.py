from django.contrib import admin
from apps.wallets.models import LedgerEntry, SystemAccount, Wallet, WalletStatus


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("wallet_number", "user", "currency", "available_balance", "hold_balance", "current_balance", "status", "updated_at")
    search_fields = ("wallet_number", "user__email", "user__full_name", "user__phone_number")
    list_filter = ("status", "currency", "created_at")
    readonly_fields = ("id", "wallet_number", "user", "currency", "available_balance", "hold_balance", "current_balance", "created_at", "updated_at")
    fields = ("id", "wallet_number", "user", "currency", "available_balance", "hold_balance", "current_balance", "status", "is_primary", "created_at", "updated_at")
    actions = ("freeze_wallets", "activate_wallets")

    @admin.action(description="Freeze selected wallets")
    def freeze_wallets(self, request, queryset):
        queryset.update(status=WalletStatus.FROZEN)

    @admin.action(description="Activate selected wallets")
    def activate_wallets(self, request, queryset):
        queryset.update(status=WalletStatus.ACTIVE)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SystemAccount)
class SystemAccountAdmin(admin.ModelAdmin):
    list_display = ("account_code", "account_name", "currency", "balance", "updated_at")
    readonly_fields = ("id", "account_code", "balance", "created_at", "updated_at")
    search_fields = ("account_code", "account_name")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "transaction", "wallet", "system_account", "entry_type", "amount", "balance_before", "balance_after", "created_at")
    list_filter = ("entry_type", "created_at")
    search_fields = ("transaction__transaction_code", "wallet__wallet_number", "system_account__account_code")
    readonly_fields = ("id", "transaction", "wallet", "system_account", "entry_type", "amount", "balance_before", "balance_after", "description", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
