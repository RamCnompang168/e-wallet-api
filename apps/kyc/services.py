import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BankingException
from apps.kyc.models import KYCDocument, KYCReview, KYCStatus, KYCVerification
from apps.users.models import AuditLog, User

logger = logging.getLogger("banking.kyc")


class KYCService:
    """Manages identity verification submissions and compliance reviews."""

    @classmethod
    def submit_kyc_application(
        cls,
        user: User,
        target_tier: int,
        document_type: str,
        document_number: str,
        front_image,
        back_image=None,
        selfie_image=None
    ) -> KYCVerification:
        # Check if user already has an active pending verification
        if KYCVerification.objects.filter(user=user, status=KYCStatus.PENDING).exists():
            raise BankingException("A pending KYC application is already awaiting compliance review.")

        if user.kyc_tier >= target_tier:
            raise BankingException(f"You already hold KYC Tier {user.kyc_tier}.")

        with transaction.atomic():
            verification = KYCVerification.objects.create(
                user=user,
                target_tier=target_tier,
                status=KYCStatus.PENDING
            )

            KYCDocument.objects.create(
                verification=verification,
                document_type=document_type,
                document_number=document_number,
                front_image=front_image,
                back_image=back_image,
                selfie_image=selfie_image
            )

            AuditLog.objects.create(
                user=user,
                action="KYC_SUBMITTED",
                entity_type="KYCVerification",
                entity_id=str(verification.id),
                new_value={"tier": target_tier, "doc_type": document_type}
            )

        return verification

    @classmethod
    def review_kyc_application(
        cls,
        reviewer: User,
        verification_id: str,
        decision: str,
        rejection_reason: str = "",
        notes: str = ""
    ) -> KYCVerification:
        if not reviewer.is_admin_or_staff:
            raise PermissionDenied("Compliance or Admin authorization is required to review KYC.")

        try:
            verification = KYCVerification.objects.select_related("user").get(id=verification_id)
        except KYCVerification.DoesNotExist:
            raise BankingException("KYC verification application not found.")

        if verification.status != KYCStatus.PENDING:
            raise BankingException(f"Application has already been processed with status {verification.status}.")

        with transaction.atomic():
            now = timezone.now()
            if decision == KYCStatus.APPROVED:
                verification.status = KYCStatus.APPROVED
                verification.completed_at = now
                verification.save(update_fields=["status", "completed_at", "updated_at"])

                # Elevate user's KYC tier
                user = verification.user
                user.kyc_tier = verification.target_tier
                user.save(update_fields=["kyc_tier", "updated_at"])

            elif decision == KYCStatus.REJECTED:
                if not rejection_reason:
                    raise ValidationError("A rejection reason is required when rejecting a KYC submission.")
                verification.status = KYCStatus.REJECTED
                verification.completed_at = now
                verification.save(update_fields=["status", "completed_at", "updated_at"])
            else:
                raise ValidationError("Decision must be either APPROVED or REJECTED.")

            KYCReview.objects.create(
                verification=verification,
                reviewer=reviewer,
                decision=decision,
                rejection_reason=rejection_reason,
                notes=notes
            )

            AuditLog.objects.create(
                user=reviewer,
                action=f"KYC_{decision}",
                entity_type="KYCVerification",
                entity_id=str(verification.id),
                new_value={"decision": decision, "reason": rejection_reason}
            )

            # Trigger notification
            from apps.notifications.services import NotificationService
            NotificationService.notify_kyc_result(verification, decision, rejection_reason)

        return verification
