from django.contrib import admin
from apps.authentication.models import OTPCode


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("purpose", "phone_number", "email", "user", "attempt_count", "is_used", "expires_at", "created_at")
    list_filter = ("purpose", "is_used", "created_at")
    search_fields = ("phone_number", "email", "user__email")
    readonly_fields = ("id", "user", "phone_number", "email", "otp_code_hash", "purpose", "expires_at", "verified_at", "attempt_count", "is_used", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
