from decimal import Decimal
from django.db import models
from django.db.models import Q
from apps.core.models import BaseModel
from apps.transactions.models import Transaction


class PaymentMethodType(models.TextChoices):
    CARD = "CARD", "Debit / Credit Card"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Direct Transfer"
    DIGITAL_WALLET = "DIGITAL_WALLET", "External Digital Wallet"
    CASH_AGENT = "CASH_AGENT", "Cash Deposit Agent"


class PaymentMethod(BaseModel):
    """Supported external payment routes and rails."""
    method_name = models.CharField(max_length=100)
    method_type = models.CharField(max_length=30, choices=PaymentMethodType.choices)
    provider_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"

    def __str__(self):
        return f"{self.method_name} ({self.provider_name}) [{self.method_type}]"


class TopUpStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Inbound Gateway"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class TopUp(BaseModel):
    """Inbound wallet funding transaction metadata."""
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="topup_details"
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name="topups"
    )
    provider_reference = models.CharField(max_length=150, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    status = models.CharField(max_length=30, choices=TopUpStatus.choices, default=TopUpStatus.PENDING, db_index=True)

    class Meta:
        verbose_name = "Top Up"
        verbose_name_plural = "Top Ups"

    def __str__(self):
        return f"TopUp {self.amount} via {self.payment_method.method_name} ({self.status})"


class WithdrawalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Settlement"
    PROCESSING = "PROCESSING", "Dispatched to Rail"
    COMPLETED = "COMPLETED", "Settled & Dispatched"
    FAILED = "FAILED", "Failed"
    REJECTED = "REJECTED", "Rejected by Compliance"


class Withdrawal(BaseModel):
    """Outbound wallet fund withdrawal metadata."""
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="withdrawal_details"
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name="withdrawals"
    )
    destination_account = models.CharField(max_length=150)
    provider_reference = models.CharField(max_length=150, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    status = models.CharField(max_length=30, choices=WithdrawalStatus.choices, default=WithdrawalStatus.PENDING, db_index=True)

    class Meta:
        verbose_name = "Withdrawal"
        verbose_name_plural = "Withdrawals"

    def __str__(self):
        return f"Withdrawal {self.amount} to {self.destination_account} ({self.status})"
