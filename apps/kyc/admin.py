from django.contrib import admin
from apps.kyc.models import KYCDocument, KYCReview, KYCVerification


class KYCDocumentInline(admin.TabularInline):
    model = KYCDocument
    extra = 0
    readonly_fields = ("document_type", "document_number", "front_image", "back_image", "selfie_image", "created_at")
    can_delete = False


class KYCReviewInline(admin.TabularInline):
    model = KYCReview
    extra = 0
    readonly_fields = ("reviewer", "decision", "rejection_reason", "notes", "created_at")
    can_delete = False


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "target_tier", "status", "completed_at", "created_at")
    list_filter = ("status", "target_tier", "created_at")
    search_fields = ("user__email", "user__full_name")
    readonly_fields = ("id", "user", "target_tier", "status", "completed_at", "created_at", "updated_at")
    inlines = [KYCDocumentInline, KYCReviewInline]

    def has_add_permission(self, request):
        return False


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("verification", "document_type", "document_number", "created_at")
    search_fields = ("verification__user__email", "document_number")
    readonly_fields = ("id", "verification", "document_type", "document_number", "front_image", "back_image", "selfie_image", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(KYCReview)
class KYCReviewAdmin(admin.ModelAdmin):
    list_display = ("verification", "reviewer", "decision", "created_at")
    search_fields = ("verification__user__email", "reviewer__email")
    readonly_fields = ("id", "verification", "reviewer", "decision", "rejection_reason", "notes", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
