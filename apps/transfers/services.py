import logging
from decimal import Decimal
from typing import Optional, Tuple
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.exceptions import (
    BankingException,
    InsufficientBalanceException,
    LimitExceededException,
    SelfTransferException,
    WalletInactiveException,
)
from apps.transactions.models import FeeRule, Transaction, TransactionLimit, TransactionStatus, TransactionType
from apps.users.models import AuditLog, User
from apps.wallets.models import Wallet
from apps.wallets.services import LedgerService

logger = logging.getLogger("banking.transfers")


class TransferService:
    """Orchestrates secure P2P transfers with limit checks, canonical locking, and ledger journaling."""

    @classmethod
    def check_transaction_limits(cls, user: User, amount: Decimal, currency: str = "USD") -> None:
        """Enforces per-transaction, daily velocity, and monthly cumulative limits."""
        limit = TransactionLimit.objects.filter(
            role=user.role,
            kyc_tier=user.kyc_tier,
            transaction_type=TransactionType.TRANSFER,
            currency=currency,
            is_active=True
        ).first()

        if not limit:
            # Safe default fallback limit if unconfigured
            if amount > Decimal("5000.0000") and user.kyc_tier == 0:
                raise LimitExceededException(
                    "Unverified users are restricted to transfers under 5,000 USD. Complete KYC to raise limit."
                )
            return

        if amount < limit.minimum_amount:
            raise LimitExceededException(f"Minimum transfer amount is {limit.minimum_amount} {currency}.")

        if amount > limit.maximum_per_transaction:
            raise LimitExceededException(
                f"Amount exceeds maximum per-transaction limit of {limit.maximum_per_transaction} {currency}."
            )

        now = timezone.now()

        # Daily velocity limit
        daily_total = Transaction.objects.filter(
            sender_wallet__user=user,
            transaction_type=TransactionType.TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__date=now.date()
        ).aggregate(sum=Sum("amount"))["sum"] or Decimal("0.0000")

        if daily_total + amount > limit.maximum_per_day:
            raise LimitExceededException(
                f"Daily limit of {limit.maximum_per_day} {currency} reached. "
                f"Today's processed: {daily_total} {currency}."
            )

        # Monthly cumulative limit
        monthly_total = Transaction.objects.filter(
            sender_wallet__user=user,
            transaction_type=TransactionType.TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__year=now.year,
            created_at__month=now.month
        ).aggregate(sum=Sum("amount"))["sum"] or Decimal("0.0000")

        if monthly_total + amount > limit.maximum_per_month:
            raise LimitExceededException(
                f"Monthly limit of {limit.maximum_per_month} {currency} reached."
            )

    @classmethod
    def calculate_transfer_fee(cls, amount: Decimal) -> Decimal:
        """Calculates applicable fee based on dynamic fee rule."""
        rule = FeeRule.objects.filter(transaction_type=TransactionType.TRANSFER, is_active=True).first()
        if not rule:
            return Decimal("0.0000")
        return rule.calculate_fee(amount)

    @classmethod
    def execute_transfer(
        cls,
        sender_user: User,
        receiver_wallet_number: str,
        amount: Decimal,
        description: str = "",
        reference_number: str = "",
        pin: Optional[str] = None
    ) -> Transaction:
        """
        Executes an atomic transfer between sender and receiver wallets.
        Guarantees all-or-nothing rollback on any failure.
        """
        if amount <= Decimal("0.0000"):
            raise BankingException("Transfer amount must be strictly positive.")

        # 1. Verify User PIN if configured
        if sender_user.pin_hash:
            if not pin:
                raise BankingException("Transaction PIN is required to authorize transfer.")
            sender_user.verify_pin(pin)

        # 2. Locate Sender Active Wallet
        sender_wallet = Wallet.objects.filter(user=sender_user, is_primary=True, status="ACTIVE").first()
        if not sender_wallet:
            raise WalletInactiveException("Sender does not have an active primary wallet.")

        # 3. Locate Receiver Wallet (by wallet number, phone number, email, or username)
        query_val = receiver_wallet_number.strip()
        receiver_wallet = (
            Wallet.objects.select_related("user")
            .filter(
                Q(wallet_number__iexact=query_val)
                | Q(user__phone_number=query_val)
                | Q(user__phone_number=f"+855{query_val.lstrip('0')}" if query_val.startswith("0") else query_val)
                | Q(user__email__iexact=query_val)
                | Q(user__full_name__iexact=query_val),
                status="ACTIVE",
            )
            .order_by("-is_primary")
            .first()
        )

        is_external_bakong = False
        if not receiver_wallet:
            if "@" in query_val or query_val.lower().startswith("bakong") or query_val.startswith("0002"):
                is_external_bakong = True
            else:
                raise WalletInactiveException("Receiver wallet not found or inactive.")

        if receiver_wallet and sender_wallet.id == receiver_wallet.id:
            raise SelfTransferException("Sender and receiver wallets cannot be identical.")

        # 4. Check Limits
        cls.check_transaction_limits(sender_user, amount, currency=sender_wallet.currency)

        # 5. Calculate Fee
        fee_amount = cls.calculate_transfer_fee(amount)
        total_amount = amount + fee_amount

        # 6. Execute atomic transfer with canonical locking
        with transaction.atomic():
            if is_external_bakong:
                locked_sender = Wallet.objects.select_for_update().get(id=sender_wallet.id)
                if not locked_sender.is_active:
                    raise WalletInactiveException("Sender wallet is not active.")
                if locked_sender.available_balance < total_amount:
                    raise InsufficientBalanceException(
                        f"Available balance ({locked_sender.available_balance}) is less than required total ({total_amount})."
                    )

                payee_display = (
                    f"{query_val.split('@')[0].replace('_', ' ').title()} ({query_val.split('@')[1].upper()})"
                    if "@" in query_val else query_val
                )

                txn = Transaction.objects.create(
                    transaction_type=TransactionType.TRANSFER,
                    status=TransactionStatus.PROCESSING,
                    sender_wallet=locked_sender,
                    receiver_wallet=None,
                    amount=amount,
                    fee_amount=fee_amount,
                    total_amount=total_amount,
                    currency=locked_sender.currency,
                    description=description or f"Bakong KHQR Payment to {payee_display}",
                    reference_number=reference_number or "",
                    metadata={
                        "external_account": query_val,
                        "payment_channel": "BAKONG_KHQR",
                        "payee_name": payee_display,
                    },
                )

                LedgerService.post_external_payment_entries(
                    txn=txn,
                    sender_wallet=locked_sender,
                    amount=amount,
                    fee_amount=fee_amount,
                    channel="Bakong KHQR",
                )

                txn.transition_to(TransactionStatus.COMPLETED)
                txn.save(update_fields=["status", "completed_at", "updated_at"])

                transaction.on_commit(
                    lambda: cls._dispatch_transfer_notifications(txn)
                )

                AuditLog.objects.create(
                    user=sender_user,
                    action="TRANSFER_COMPLETED",
                    entity_type="Transaction",
                    entity_id=str(txn.id),
                    new_value={
                        "code": txn.transaction_code,
                        "amount": str(txn.amount),
                        "fee": str(txn.fee_amount),
                        "receiver": query_val,
                        "channel": "BAKONG_KHQR",
                    }
                )

                return txn

            locked = LedgerService.lock_wallets_canonical(sender_wallet.id, receiver_wallet.id)
            locked_sender = locked[str(sender_wallet.id)]
            locked_receiver = locked[str(receiver_wallet.id)]

            # Pre-flight balance check inside lock
            if locked_sender.available_balance < total_amount:
                raise InsufficientBalanceException(
                    f"Available balance ({locked_sender.available_balance}) is less than required total ({total_amount})."
                )

            # Create Transaction record
            txn = Transaction.objects.create(
                transaction_type=TransactionType.TRANSFER,
                status=TransactionStatus.PROCESSING,
                sender_wallet=locked_sender,
                receiver_wallet=locked_receiver,
                amount=amount,
                fee_amount=fee_amount,
                total_amount=total_amount,
                currency=locked_sender.currency,
                description=description or f"Transfer from {sender_user.full_name}",
                reference_number=reference_number or "",
            )

            # Record double-entry ledger journal
            LedgerService.post_transfer_entries(
                txn=txn,
                sender_wallet=locked_sender,
                receiver_wallet=locked_receiver,
                amount=amount,
                fee_amount=fee_amount
            )

            # Mark transaction completed
            txn.transition_to(TransactionStatus.COMPLETED)
            txn.save(update_fields=["status", "completed_at", "updated_at"])

            # Post-commit notification hook
            transaction.on_commit(
                lambda: cls._dispatch_transfer_notifications(txn)
            )

            AuditLog.objects.create(
                user=sender_user,
                action="TRANSFER_COMPLETED",
                entity_type="Transaction",
                entity_id=str(txn.id),
                new_value={
                    "code": txn.transaction_code,
                    "amount": str(txn.amount),
                    "fee": str(txn.fee_amount),
                    "receiver": receiver_wallet.wallet_number,
                }
            )

        return txn

    @staticmethod
    def _dispatch_transfer_notifications(txn: Transaction) -> None:
        """Asynchronously dispatches notifications for sender and receiver."""
        from apps.notifications.services import NotificationService
        NotificationService.notify_transfer_parties(txn)
