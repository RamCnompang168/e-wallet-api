from django.contrib import admin
from apps.merchants.models import (
    Merchant,
    MerchantPayment,
    Refund,
    TransactionDispute,
    TransactionReversal,
)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("business_name", "merchant_code", "owner", "status", "fee_rate", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("business_name", "merchant_code", "owner__email")
    readonly_fields = ("id", "merchant_code", "created_at", "updated_at")


@admin.register(MerchantPayment)
class MerchantPaymentAdmin(admin.ModelAdmin):
    list_display = ("merchant", "transaction", "payment_reference", "created_at")
    search_fields = ("merchant__business_name", "transaction__transaction_code", "payment_reference")
    readonly_fields = ("id", "transaction", "merchant", "payment_reference", "customer_note", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("refund_code", "original_transaction", "amount", "status", "reason", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("refund_code", "original_transaction__transaction_code")
    readonly_fields = ("id", "refund_code", "original_transaction", "refund_transaction", "merchant", "amount", "reason", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(TransactionDispute)
class TransactionDisputeAdmin(admin.ModelAdmin):
    list_display = ("dispute_code", "transaction", "claimant", "dispute_type", "status", "reviewer", "resolved_at")
    list_filter = ("dispute_type", "status")
    search_fields = ("dispute_code", "transaction__transaction_code", "claimant__email")
    readonly_fields = ("id", "dispute_code", "transaction", "claimant", "dispute_type", "reason", "evidence_file", "created_at", "updated_at")


@admin.register(TransactionReversal)
class TransactionReversalAdmin(admin.ModelAdmin):
    list_display = ("reversal_code", "original_transaction", "initiated_by", "reason", "created_at")
    search_fields = ("reversal_code", "original_transaction__transaction_code")
    readonly_fields = ("id", "reversal_code", "original_transaction", "reversal_transaction", "initiated_by", "reason", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
