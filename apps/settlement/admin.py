from django.contrib import admin
from apps.settlement.models import ReconciliationBatch, ReconciliationRecord, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "external_event_id", "event_type", "status", "retry_count", "processed_at", "created_at")
    list_filter = ("provider", "status", "created_at")
    search_fields = ("external_event_id", "provider", "event_type")
    readonly_fields = ("id", "provider", "external_event_id", "event_type", "payload", "signature", "status", "retry_count", "processed_at", "error_message", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


class ReconciliationRecordInline(admin.TabularInline):
    model = ReconciliationRecord
    extra = 0
    readonly_fields = ("external_reference", "internal_transaction", "internal_amount", "external_amount", "status", "discrepancy_details")
    can_delete = False


@admin.register(ReconciliationBatch)
class ReconciliationBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_code", "provider", "reconciliation_date", "total_internal_records", "total_external_records", "matched_count", "mismatch_count", "status", "created_at")
    list_filter = ("provider", "status", "reconciliation_date")
    search_fields = ("batch_code", "provider")
    readonly_fields = ("id", "batch_code", "provider", "reconciliation_date", "total_internal_records", "total_external_records", "matched_count", "mismatch_count", "status", "created_at", "updated_at")
    inlines = [ReconciliationRecordInline]

    def has_add_permission(self, request):
        return False


@admin.register(ReconciliationRecord)
class ReconciliationRecordAdmin(admin.ModelAdmin):
    list_display = ("batch", "external_reference", "internal_amount", "external_amount", "status")
    list_filter = ("status",)
    search_fields = ("external_reference", "batch__batch_code")
    readonly_fields = ("id", "batch", "internal_transaction", "external_reference", "internal_amount", "external_amount", "status", "discrepancy_details", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
