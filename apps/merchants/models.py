import secrets
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.core.models import BaseModel
from apps.transactions.models import Transaction


def generate_merchant_code() -> str:
    return f"MCH-{secrets.token_hex(4).upper()}"


def generate_refund_code() -> str:
    return f"REF-{secrets.token_hex(6).upper()}"


def generate_dispute_code() -> str:
    return f"DSP-{secrets.token_hex(6).upper()}"


def generate_reversal_code() -> str:
    return f"REV-{secrets.token_hex(6).upper()}"


class MerchantStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    CLOSED = "CLOSED", "Closed"


class Merchant(BaseModel):
    """Business merchant profile."""
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="merchant_profile"
    )
    business_name = models.CharField(max_length=150)
    merchant_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        default=generate_merchant_code,
        editable=False
    )
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=30, choices=MerchantStatus.choices, default=MerchantStatus.ACTIVE, db_index=True)
    fee_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0150"))  # 1.5% MDR

    class Meta:
        verbose_name = "Merchant"
        verbose_name_plural = "Merchants"

    def __str__(self):
        return f"{self.business_name} ({self.merchant_code}) [{self.status}]"


class MerchantPayment(BaseModel):
    """Payment record linked to a merchant transaction."""
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="merchant_payment_details"
    )
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name="payments"
    )
    payment_reference = models.CharField(max_length=150, blank=True, db_index=True)
    customer_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Merchant Payment"
        verbose_name_plural = "Merchant Payments"

    def __str__(self):
        return f"Payment to {self.merchant.business_name} [{self.transaction.transaction_code}]"


class RefundStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Execution"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class Refund(BaseModel):
    """Tracks full or partial refunds for merchant or peer transactions."""
    refund_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_refund_code,
        editable=False
    )
    original_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name="refunds"
    )
    refund_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="as_refund"
    )
    merchant = models.ForeignKey(
        Merchant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="refunds"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=RefundStatus.choices, default=RefundStatus.PENDING, db_index=True)

    class Meta:
        verbose_name = "Refund"
        verbose_name_plural = "Refunds"

    def __str__(self):
        return f"Refund {self.refund_code} for Txn {self.original_transaction.transaction_code} ({self.amount})"


class DisputeType(models.TextChoices):
    UNAUTHORIZED_CHARGE = "UNAUTHORIZED_CHARGE", "Unauthorized Charge"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED", "Goods / Services Not Received"
    DEFECTIVE_GOODS = "DEFECTIVE_GOODS", "Defective or Not as Described"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE", "Duplicate Charge"
    OTHER = "OTHER", "Other Issue"


class DisputeStatus(models.TextChoices):
    OPEN = "OPEN", "Dispute Opened"
    UNDER_REVIEW = "UNDER_REVIEW", "Under Review by Compliance"
    ACCEPTED = "ACCEPTED", "Dispute Accepted (Refunded)"
    REJECTED = "REJECTED", "Dispute Rejected"


class TransactionDispute(BaseModel):
    """Customer initiated dispute ticket regarding a transaction."""
    dispute_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_dispute_code,
        editable=False
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name="disputes"
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="filed_disputes"
    )
    dispute_type = models.CharField(max_length=40, choices=DisputeType.choices)
    reason = models.TextField()
    evidence_file = models.FileField(upload_to="disputes/%Y/%m/", null=True, blank=True)
    status = models.CharField(max_length=30, choices=DisputeStatus.choices, default=DisputeStatus.OPEN, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_disputes"
    )
    resolution_notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Transaction Dispute"
        verbose_name_plural = "Transaction Disputes"

    def __str__(self):
        return f"Dispute {self.dispute_code} [{self.status}] on {self.transaction.transaction_code}"


class TransactionReversal(BaseModel):
    """Administrative full reversal of an erroneous or fraudulent transaction."""
    reversal_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_reversal_code,
        editable=False
    )
    original_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="reversal"
    )
    reversal_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="as_reversal"
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="initiated_reversals"
    )
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=30, default="COMPLETED")

    class Meta:
        verbose_name = "Transaction Reversal"
        verbose_name_plural = "Transaction Reversals"

    def __str__(self):
        return f"Reversal {self.reversal_code} for {self.original_transaction.transaction_code}"
