from django.conf import settings
from django.db import models
from apps.core.models import BaseModel


class KYCStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Compliance Review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class DocumentType(models.TextChoices):
    PASSPORT = "PASSPORT", "International Passport"
    NATIONAL_ID = "NATIONAL_ID", "National Identity Card"
    DRIVING_LICENSE = "DRIVING_LICENSE", "Driving License"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS", "Utility Bill / Bank Statement"


class KYCVerification(BaseModel):
    """Lifecycle record for a user's KYC tier upgrade application."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="kyc_verifications"
    )
    target_tier = models.PositiveSmallIntegerField(default=1)  # 1: Basic, 2: Enhanced
    status = models.CharField(max_length=30, choices=KYCStatus.choices, default=KYCStatus.PENDING, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "KYC Verification"
        verbose_name_plural = "KYC Verifications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"KYC Tier {self.target_tier} for {self.user.email} ({self.status})"


class KYCDocument(BaseModel):
    """Document evidence submitted for identity verification."""
    verification = models.ForeignKey(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name="documents"
    )
    document_type = models.CharField(max_length=40, choices=DocumentType.choices)
    document_number = models.CharField(max_length=100, blank=True, default="")
    front_image = models.FileField(upload_to="kyc_vault/%Y/%m/")
    back_image = models.FileField(upload_to="kyc_vault/%Y/%m/", null=True, blank=True)
    selfie_image = models.FileField(upload_to="kyc_vault/%Y/%m/", null=True, blank=True)

    class Meta:
        verbose_name = "KYC Document"
        verbose_name_plural = "KYC Documents"

    def __str__(self):
        return f"{self.document_type} [{self.document_number}] for {self.verification.user.email}"


class KYCReview(BaseModel):
    """Audit log of compliance reviewer decisions."""
    verification = models.ForeignKey(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name="reviews"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conducted_kyc_reviews"
    )
    decision = models.CharField(max_length=20, choices=[(KYCStatus.APPROVED, "Approved"), (KYCStatus.REJECTED, "Rejected")])
    rejection_reason = models.CharField(max_length=500, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "KYC Review"
        verbose_name_plural = "KYC Reviews"

    def __str__(self):
        return f"Review by {self.reviewer.email}: {self.decision} on {self.verification_id}"
