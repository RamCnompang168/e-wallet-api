from django.contrib import admin
from apps.transactions.models import FeeRule, Transaction, TransactionLimit


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_code", "transaction_type", "sender_wallet", "receiver_wallet", "amount", "fee_amount", "currency", "status", "created_at")
    search_fields = ("transaction_code", "reference_number", "sender_wallet__wallet_number", "receiver_wallet__wallet_number")
    list_filter = ("transaction_type", "status", "currency", "created_at")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "transaction_code", "sender_wallet", "receiver_wallet", "amount", "fee_amount", "total_amount", "currency", "transaction_type", "status", "description", "reference_number", "parent_transaction", "metadata", "completed_at", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TransactionLimit)
class TransactionLimitAdmin(admin.ModelAdmin):
    list_display = ("role", "kyc_tier", "transaction_type", "currency", "minimum_amount", "maximum_per_transaction", "maximum_per_day", "maximum_per_month", "is_active")
    list_filter = ("role", "kyc_tier", "transaction_type", "is_active")


@admin.register(FeeRule)
class FeeRuleAdmin(admin.ModelAdmin):
    list_display = ("transaction_type", "fixed_fee", "percentage_fee", "min_fee", "max_fee", "is_active")
    list_filter = ("is_active",)
