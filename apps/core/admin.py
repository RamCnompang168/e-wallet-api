from django.contrib import admin
from apps.core.models import IdempotencyKey


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ("key", "user", "status", "response_code", "expires_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("key", "user__email", "request_path")
    readonly_fields = ("id", "user", "key", "request_path", "request_params_hash", "status", "response_code", "response_body", "expires_at", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
