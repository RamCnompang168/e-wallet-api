from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from apps.users.models import AuditLog, SecurityEvent, User, UserDevice, UserSession, UserStatus

admin.site.site_header = "NovaPay Banking & E-Wallet Operations"
admin.site.site_title = "NovaPay Portal"
admin.site.index_title = "Banking Administration"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    ordering = ("email",)
    list_display = ("email", "full_name", "phone_number", "id_document_type", "id_document_number", "role", "status", "kyc_tier", "is_staff")
    list_filter = ("role", "status", "id_document_type", "kyc_tier", "is_staff", "is_active")
    search_fields = ("email", "full_name", "phone_number", "id_document_number")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile Info", {"fields": ("full_name", "phone_number", "date_of_birth", "gender", "profile_photo")}),
        ("Identity Verification Document", {"fields": ("id_document_type", "id_document_number", "id_document_photo")}),
        ("Banking Security & KYC", {"fields": ("role", "status", "kyc_tier", "pin_hash", "pin_retry_count", "pin_locked_until")}),
        ("Verification Status", {"fields": ("is_email_verified", "is_phone_verified")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("last_login_at", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login_at")
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "phone_number", "full_name", "role", "password")
        }),
    )
    actions = ["approve_selected_users", "reject_selected_users", "suspend_selected_users"]

    @admin.action(description="Approve selected user accounts (Activate)")
    def approve_selected_users(self, request, queryset):
        from apps.wallets.models import Wallet
        updated = 0
        for user in queryset:
            user.status = UserStatus.ACTIVE
            user.is_active = True
            user.kyc_tier = max(user.kyc_tier, 1)
            user.save(update_fields=["status", "is_active", "kyc_tier", "updated_at"])
            Wallet.objects.filter(user=user, is_primary=True).update(status="ACTIVE")
            updated += 1
        self.message_user(request, f"{updated} user(s) approved and activated successfully.")

    @admin.action(description="Reject selected user accounts")
    def reject_selected_users(self, request, queryset):
        updated = queryset.update(status=UserStatus.REJECTED, is_active=False)
        self.message_user(request, f"{updated} user(s) rejected.")

    @admin.action(description="Suspend selected user accounts")
    def suspend_selected_users(self, request, queryset):
        updated = queryset.update(status=UserStatus.SUSPENDED)
        self.message_user(request, f"{updated} user(s) suspended.")


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "device_type", "device_identifier", "is_trusted", "is_active", "last_login_at")
    list_filter = ("device_type", "is_trusted", "is_active")
    search_fields = ("user__email", "device_identifier", "device_name")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device", "ip_address", "is_revoked", "expires_at", "created_at")
    list_filter = ("is_revoked",)
    search_fields = ("user__email", "ip_address", "refresh_token_hash")


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "ip_address", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__email", "ip_address", "event_type")
    readonly_fields = ("id", "user", "event_type", "ip_address", "user_agent", "details", "created_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "entity_type", "entity_id", "user", "ip_address", "created_at")
    list_filter = ("action", "entity_type", "created_at")
    search_fields = ("action", "entity_type", "entity_id", "user__email")
    readonly_fields = ("id", "user", "action", "entity_type", "entity_id", "old_value", "new_value", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
