from django.contrib import admin
from apps.payments.models import PaymentMethod, TopUp, Withdrawal


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("method_name", "provider_name", "method_type", "is_active", "created_at")
    list_filter = ("method_type", "is_active")
    search_fields = ("method_name", "provider_name")


@admin.register(TopUp)
class TopUpAdmin(admin.ModelAdmin):
    list_display = ("transaction", "payment_method", "amount", "fee_amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("transaction__transaction_code", "provider_reference")
    readonly_fields = ("id", "transaction", "payment_method", "provider_reference", "amount", "fee_amount", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("transaction", "destination_account", "amount", "fee_amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("transaction__transaction_code", "destination_account", "provider_reference")
    readonly_fields = ("id", "transaction", "payment_method", "destination_account", "provider_reference", "amount", "fee_amount", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
