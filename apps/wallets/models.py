import secrets
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel


def generate_wallet_number() -> str:
    """Generates a secure, human-readable unique wallet number: WAL-XXXXXXXX."""
    random_digits = "".join(str(secrets.randbelow(10)) for _ in range(8))
    return f"WAL-{random_digits}"


class WalletStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    FROZEN = "FROZEN", "Frozen"
    CLOSED = "CLOSED", "Closed"


class Wallet(BaseModel):
    """
    User wallet account entity.
    Maintains cached current, available, and hold balances.
    Authoritative state is tracked via immutable LedgerEntry journal records.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallets"
    )
    wallet_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        default=generate_wallet_number,
        editable=False
    )
    currency = models.CharField(max_length=3, default="USD")
    current_balance = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )
    available_balance = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )
    hold_balance = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )
    status = models.CharField(
        max_length=20,
        choices=WalletStatus.choices,
        default=WalletStatus.ACTIVE,
        db_index=True
    )
    is_primary = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"
        constraints = [
            models.CheckConstraint(
                condition=Q(available_balance__gte=Decimal("0.0000")),
                name="wallet_available_balance_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(hold_balance__gte=Decimal("0.0000")),
                name="wallet_hold_balance_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(current_balance__gte=Decimal("0.0000")),
                name="wallet_current_balance_non_negative"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["wallet_number", "status"]),
        ]

    def __str__(self):
        return f"{self.wallet_number} ({self.currency}) - User: {self.user.email} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status == WalletStatus.ACTIVE


class SystemAccountCode(models.TextChoices):
    FEE_REVENUE = "SYSTEM_FEE_REVENUE", "Platform Fee Revenue Account"
    SETTLEMENT_ESCROW = "SYSTEM_SETTLEMENT_ESCROW", "Settlement & Escrow Clearing"
    EXTERNAL_CLEARING = "SYSTEM_EXTERNAL_CLEARING", "External Cash-In / Cash-Out Clearing"


class SystemAccount(BaseModel):
    """
    Internal platform balancing accounts used to enforce the double-entry
    accounting invariant: Total Debits == Total Credits across all platform movements.
    """
    account_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        choices=SystemAccountCode.choices
    )
    account_name = models.CharField(max_length=150)
    currency = models.CharField(max_length=3, default="USD")
    balance = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000")
    )
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "System Account"
        verbose_name_plural = "System Accounts"

    def __str__(self):
        return f"{self.account_name} ({self.account_code}) - Bal: {self.balance} {self.currency}"

    @classmethod
    def get_or_create_system_account(cls, code: str, currency: str = "USD") -> "SystemAccount":
        account, _ = cls.objects.get_or_create(
            account_code=code,
            defaults={
                "account_name": dict(SystemAccountCode.choices).get(code, code),
                "currency": currency,
                "balance": Decimal("0.0000")
            }
        )
        return account


class LedgerEntryType(models.TextChoices):
    DEBIT = "DEBIT", "Debit (Deduction / Asset Increase)"
    CREDIT = "CREDIT", "Credit (Addition / Liability Increase)"


class LedgerEntry(models.Model):
    """
    Authoritative, immutable journal of every monetary debit and credit.
    Never update or delete an existing LedgerEntry.
    """
    id = models.BigAutoField(primary_key=True)
    transaction = models.ForeignKey(
        "transactions.Transaction",
        on_delete=models.PROTECT,
        related_name="ledger_entries"
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries"
    )
    system_account = models.ForeignKey(
        SystemAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=10, choices=LedgerEntryType.choices, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    balance_before = models.DecimalField(max_digits=18, decimal_places=4)
    balance_after = models.DecimalField(max_digits=18, decimal_places=4)
    description = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Ledger Entry"
        verbose_name_plural = "Ledger Entries"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=Decimal("0.0000")),
                name="ledger_amount_strictly_positive"
            ),
            models.CheckConstraint(
                condition=Q(wallet__isnull=False) | Q(system_account__isnull=False),
                name="ledger_entry_target_required"
            )
        ]
        indexes = [
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["system_account", "created_at"]),
            models.Index(fields=["transaction", "entry_type"]),
        ]

    def __str__(self):
        target = self.wallet.wallet_number if self.wallet else self.system_account.account_code
        return f"{self.entry_type} {self.amount} on {target} [Txn: {self.transaction_id}]"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Ledger entries are strictly immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries cannot be deleted under any circumstances.")
