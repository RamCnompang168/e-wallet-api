import secrets
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel
from apps.users.models import UserRole
from apps.wallets.models import Wallet


def generate_transaction_code() -> str:
    """Generates unique financial transaction reference code: TXN-YYYYMMDD-XXXXXXXX."""
    date_part = timezone.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(4).upper()
    return f"TXN-{date_part}-{random_part}"


class TransactionType(models.TextChoices):
    TRANSFER = "TRANSFER", "Peer-to-Peer Transfer"
    TOPUP = "TOPUP", "Wallet Top-up"
    WITHDRAWAL = "WITHDRAWAL", "Wallet Withdrawal"
    MERCHANT_PAYMENT = "MERCHANT_PAYMENT", "Merchant QR/Code Payment"
    REFUND = "REFUND", "Payment Refund"
    REVERSAL = "REVERSAL", "Transaction Administrative Reversal"
    FEE = "FEE", "System Fee Deduction"


class TransactionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Execution"
    PROCESSING = "PROCESSING", "In Settlement"
    COMPLETED = "COMPLETED", "Settled & Completed"
    FAILED = "FAILED", "Failed Execution"
    CANCELLED = "CANCELLED", "Cancelled"
    REVERSED = "REVERSED", "Reversed"
    REFUNDED = "REFUNDED", "Refunded"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"


class Transaction(BaseModel):
    """
    Central financial transaction record.
    Represents an intended or completed state machine operation.
    """
    transaction_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_transaction_code,
        editable=False
    )
    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
        db_index=True
    )
    status = models.CharField(
        max_length=30,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
        db_index=True
    )
    sender_wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sent_transactions"
    )
    receiver_wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_transactions"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    total_amount = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=3, default="USD")
    description = models.CharField(max_length=500, blank=True, default="")
    reference_number = models.CharField(max_length=100, blank=True, default="", db_index=True)

    parent_transaction = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_transactions"
    )
    metadata = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=Decimal("0.0000")),
                name="transaction_amount_strictly_positive"
            ),
            models.CheckConstraint(
                condition=Q(fee_amount__gte=Decimal("0.0000")),
                name="transaction_fee_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=models.F("amount")),
                name="transaction_total_amount_gte_amount"
            ),
        ]
        indexes = [
            models.Index(fields=["sender_wallet", "created_at"]),
            models.Index(fields=["receiver_wallet", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["transaction_type", "created_at"]),
            models.Index(fields=["reference_number"]),
        ]

    def __str__(self):
        return f"[{self.transaction_type}] {self.transaction_code} - {self.amount} {self.currency} ({self.status})"

    def transition_to(self, new_status: str) -> None:
        """Enforces safe state machine transitions."""
        valid_transitions = {
            TransactionStatus.PENDING: [TransactionStatus.PROCESSING, TransactionStatus.FAILED, TransactionStatus.CANCELLED],
            TransactionStatus.PROCESSING: [TransactionStatus.COMPLETED, TransactionStatus.FAILED],
            TransactionStatus.COMPLETED: [TransactionStatus.REVERSED, TransactionStatus.REFUNDED, TransactionStatus.PARTIALLY_REFUNDED],
            TransactionStatus.PARTIALLY_REFUNDED: [TransactionStatus.REFUNDED],
            TransactionStatus.FAILED: [],
            TransactionStatus.CANCELLED: [],
            TransactionStatus.REVERSED: [],
            TransactionStatus.REFUNDED: [],
        }

        allowed = valid_transitions.get(self.status, [])
        if new_status not in allowed:
            raise ValidationError(
                f"Invalid transaction transition: Cannot transition from {self.status} to {new_status}."
            )

        self.status = new_status
        if new_status == TransactionStatus.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()


class TransactionLimit(BaseModel):
    """Transaction limits configured per Role or KYC Tier."""
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.CUSTOMER)
    kyc_tier = models.PositiveSmallIntegerField(default=0)
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices)
    currency = models.CharField(max_length=3, default="USD")

    minimum_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("1.0000"))
    maximum_per_transaction = models.DecimalField(max_digits=18, decimal_places=4)
    maximum_per_day = models.DecimalField(max_digits=18, decimal_places=4)
    maximum_per_month = models.DecimalField(max_digits=18, decimal_places=4)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Transaction Limit"
        verbose_name_plural = "Transaction Limits"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "kyc_tier", "transaction_type", "currency"],
                name="unique_role_tier_type_limit"
            )
        ]

    def __str__(self):
        return f"Limit [{self.role} Tier {self.kyc_tier}] - {self.transaction_type} (Max: {self.maximum_per_transaction} {self.currency})"


class FeeRule(BaseModel):
    """Dynamic transaction fee calculation rules."""
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices, unique=True)
    fixed_fee = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    percentage_fee = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))  # e.g. 0.0150 = 1.5%
    min_fee = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    max_fee = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Fee Rule"
        verbose_name_plural = "Fee Rules"

    def __str__(self):
        return f"Fee for {self.transaction_type}: {self.fixed_fee} + {self.percentage_fee * 100}%"

    def calculate_fee(self, amount: Decimal) -> Decimal:
        """Calculates fee given an amount, clamped between min_fee and max_fee."""
        if not self.is_active:
            return Decimal("0.0000")
        calculated = self.fixed_fee + (amount * self.percentage_fee)
        if calculated < self.min_fee:
            calculated = self.min_fee
        if self.max_fee and calculated > self.max_fee:
            calculated = self.max_fee
        return calculated.quantize(Decimal("0.0001"))
