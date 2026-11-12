from django.contrib import admin
from apps.beneficiaries.models import Beneficiary


@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("nickname", "beneficiary_wallet", "user", "is_favorite", "created_at")
    search_fields = ("nickname", "beneficiary_wallet__wallet_number", "user__email", "user__full_name")
    list_filter = ("is_favorite", "created_at")
    readonly_fields = ("id", "created_at", "updated_at")
