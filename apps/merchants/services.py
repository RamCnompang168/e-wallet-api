import logging
from decimal import Decimal
from typing import Optional, Tuple
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import (
    BankingException,
    InsufficientBalanceException,
    InvalidTransactionStateException,
    WalletInactiveException,
)
from apps.merchants.models import (
    DisputeStatus,
    Merchant,
    MerchantPayment,
    MerchantStatus,
    Refund,
    RefundStatus,
    TransactionDispute,
    TransactionReversal,
)
from apps.transactions.models import Transaction, TransactionStatus, TransactionType
from apps.users.models import AuditLog, User
from apps.wallets.models import LedgerEntry, LedgerEntryType, SystemAccount, SystemAccountCode, Wallet
from apps.wallets.services import LedgerService

logger = logging.getLogger("banking.merchants")


class MerchantPaymentService:
    """Manages merchant QR/Code payments with Merchant Discount Rate (MDR) fee deductions."""

    @classmethod
    def execute_merchant_payment(
        cls,
        customer_user: User,
        merchant_code: str,
        amount: Decimal,
        customer_note: str = "",
        payment_reference: str = "",
        pin: Optional[str] = None
    ) -> Transaction:
        if amount <= Decimal("0.0000"):
            raise BankingException("Payment amount must be strictly positive.")

        if customer_user.pin_hash:
            if not pin:
                raise BankingException("PIN is required for merchant payment.")
            customer_user.verify_pin(pin)

        # 1. Locate Merchant and Merchant Wallet
        merchant = Merchant.objects.select_related("owner").filter(
            merchant_code=merchant_code.strip().upper(),
            status=MerchantStatus.ACTIVE
        ).first()
        if not merchant:
            raise BankingException("Merchant account not found or inactive.")

        merchant_wallet = Wallet.objects.filter(user=merchant.owner, is_primary=True, status="ACTIVE").first()
        if not merchant_wallet:
            raise WalletInactiveException("Merchant settlement wallet is not active.")

        # 2. Locate Customer Wallet
        customer_wallet = Wallet.objects.filter(user=customer_user, is_primary=True, status="ACTIVE").first()
        if not customer_wallet:
            raise WalletInactiveException("Customer primary wallet is not active.")

        if customer_wallet.id == merchant_wallet.id:
            raise BankingException("Customer and merchant wallets cannot be the same.")

        # 3. Calculate Merchant MDR fee
        mdr_fee = (amount * merchant.fee_rate).quantize(Decimal("0.0001"))
        net_merchant_credit = amount - mdr_fee

        with transaction.atomic():
            # Canonical lock
            locked = LedgerService.lock_wallets_canonical(customer_wallet.id, merchant_wallet.id)
            locked_customer = locked[str(customer_wallet.id)]
            locked_merchant = locked[str(merchant_wallet.id)]

            if locked_customer.available_balance < amount:
                raise InsufficientBalanceException("Insufficient customer balance for merchant payment.")

            txn = Transaction.objects.create(
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                status=TransactionStatus.PROCESSING,
                sender_wallet=locked_customer,
                receiver_wallet=locked_merchant,
                amount=amount,
                fee_amount=mdr_fee,
                total_amount=amount,
                currency=locked_customer.currency,
                description=f"Payment to {merchant.business_name}" + (f": {customer_note}" if customer_note else ""),
                reference_number=payment_reference or "",
            )

            # Double-entry ledger:
            # 1. DEBIT Customer: amount
            cust_before = locked_customer.available_balance
            locked_customer.available_balance -= amount
            locked_customer.current_balance -= amount
            locked_customer.save(update_fields=["available_balance", "current_balance", "updated_at"])

            LedgerEntry.objects.create(
                transaction=txn,
                wallet=locked_customer,
                entry_type=LedgerEntryType.DEBIT,
                amount=amount,
                balance_before=cust_before,
                balance_after=locked_customer.available_balance,
                description=f"Payment to merchant {merchant.business_name}"
            )

            # 2. CREDIT Merchant: net_merchant_credit
            merch_before = locked_merchant.available_balance
            locked_merchant.available_balance += net_merchant_credit
            locked_merchant.current_balance += net_merchant_credit
            locked_merchant.save(update_fields=["available_balance", "current_balance", "updated_at"])

            LedgerEntry.objects.create(
                transaction=txn,
                wallet=locked_merchant,
                entry_type=LedgerEntryType.CREDIT,
                amount=net_merchant_credit,
                balance_before=merch_before,
                balance_after=locked_merchant.available_balance,
                description=f"Payment received from {customer_user.full_name} (MDR: {mdr_fee})"
            )

            # 3. CREDIT Platform Fee Revenue: mdr_fee
            if mdr_fee > Decimal("0.0000"):
                fee_account = SystemAccount.get_or_create_system_account(
                    code=SystemAccountCode.FEE_REVENUE,
                    currency=txn.currency
                )
                fee_before = fee_account.balance
                fee_account.balance += mdr_fee
                fee_account.save(update_fields=["balance", "updated_at"])

                LedgerEntry.objects.create(
                    transaction=txn,
                    system_account=fee_account,
                    entry_type=LedgerEntryType.CREDIT,
                    amount=mdr_fee,
                    balance_before=fee_before,
                    balance_after=fee_account.balance,
                    description=f"MDR fee on {txn.transaction_code}"
                )

            MerchantPayment.objects.create(
                transaction=txn,
                merchant=merchant,
                payment_reference=payment_reference,
                customer_note=customer_note
            )

            txn.transition_to(TransactionStatus.COMPLETED)
            txn.save(update_fields=["status", "completed_at", "updated_at"])

            AuditLog.objects.create(
                user=customer_user,
                action="MERCHANT_PAYMENT_COMPLETED",
                entity_type="Transaction",
                entity_id=str(txn.id),
                new_value={"merchant": merchant.merchant_code, "amount": str(amount), "mdr_fee": str(mdr_fee)}
            )

        return txn


class RefundService:
    """Handles full and partial refunds with over-refund prevention."""

    @classmethod
    def process_refund(
        cls,
        initiator_user: User,
        original_transaction_id: str,
        amount: Decimal,
        reason: str
    ) -> Refund:
        if amount <= Decimal("0.0000"):
            raise BankingException("Refund amount must be strictly positive.")

        try:
            orig_txn = Transaction.objects.select_related("sender_wallet__user", "receiver_wallet__user").get(
                id=original_transaction_id
            )
        except Transaction.DoesNotExist:
            raise BankingException("Original transaction not found.")

        if orig_txn.status not in [TransactionStatus.COMPLETED, TransactionStatus.PARTIALLY_REFUNDED]:
            raise InvalidTransactionStateException(f"Transaction in state {orig_txn.status} cannot be refunded.")

        # Verify authorized initiator (Admin, Staff, or Receiver/Merchant)
        is_admin = initiator_user.is_admin_or_staff
        is_receiver = orig_txn.receiver_wallet and orig_txn.receiver_wallet.user_id == initiator_user.id
        if not (is_admin or is_receiver):
            raise PermissionDenied("You are not authorized to refund this transaction.")

        # Check over-refund: sum of previous completed refunds + current amount <= original amount
        previous_refunded = Refund.objects.filter(
            original_transaction=orig_txn,
            status=RefundStatus.COMPLETED
        ).aggregate(sum=Sum("amount"))["sum"] or Decimal("0.0000")

        if previous_refunded + amount > orig_txn.amount:
            max_refundable = orig_txn.amount - previous_refunded
            raise BankingException(
                f"Refund amount ({amount}) exceeds maximum refundable amount ({max_refundable})."
            )

        merchant = getattr(orig_txn, "merchant_payment_details", None)
        merchant_obj = merchant.merchant if merchant else None

        # Calculate proportional fee reversal if original transaction incurred a fee
        proportional_fee = Decimal("0.0000")
        if orig_txn.fee_amount > Decimal("0.0000") and orig_txn.amount > Decimal("0.0000"):
            proportional_fee = ((amount / orig_txn.amount) * orig_txn.fee_amount).quantize(Decimal("0.0001"))

        with transaction.atomic():
            # Lock wallets in canonical order: original receiver (now debited) and original sender (now credited)
            locked = LedgerService.lock_wallets_canonical(orig_txn.receiver_wallet_id, orig_txn.sender_wallet_id)
            refund_debtor = locked[str(orig_txn.receiver_wallet_id)]
            refund_creditor = locked[str(orig_txn.sender_wallet_id)]

            # Create Refund Transaction
            refund_txn = Transaction.objects.create(
                transaction_type=TransactionType.REFUND,
                status=TransactionStatus.PROCESSING,
                sender_wallet=refund_debtor,
                receiver_wallet=refund_creditor,
                amount=amount,
                fee_amount=proportional_fee,
                total_amount=amount,
                currency=orig_txn.currency,
                description=f"Refund for {orig_txn.transaction_code}: {reason}",
                parent_transaction=orig_txn,
            )

            # Balanced double-entry with fee reversal
            LedgerService.post_refund_entries(
                txn=refund_txn,
                debtor_wallet=refund_debtor,
                creditor_wallet=refund_creditor,
                amount=amount,
                fee_amount=proportional_fee
            )

            refund_txn.transition_to(TransactionStatus.COMPLETED)
            refund_txn.save(update_fields=["status", "completed_at", "updated_at"])

            # Create Refund record
            refund_rec = Refund.objects.create(
                original_transaction=orig_txn,
                refund_transaction=refund_txn,
                merchant=merchant_obj,
                amount=amount,
                reason=reason,
                status=RefundStatus.COMPLETED
            )

            # Update original transaction state
            if previous_refunded + amount >= orig_txn.amount:
                orig_txn.status = TransactionStatus.REFUNDED
            else:
                orig_txn.status = TransactionStatus.PARTIALLY_REFUNDED
            orig_txn.save(update_fields=["status", "updated_at"])

            AuditLog.objects.create(
                user=initiator_user,
                action="REFUND_ISSUED",
                entity_type="Refund",
                entity_id=str(refund_rec.id),
                new_value={"original_txn": orig_txn.transaction_code, "amount": str(amount), "reason": reason}
            )

        return refund_rec


class DisputeService:
    """Manages transaction dispute lifecycles and compliance resolutions."""

    @classmethod
    def file_dispute(
        cls,
        user: User,
        transaction_id: str,
        dispute_type: str,
        reason: str,
        evidence_file=None
    ) -> TransactionDispute:
        try:
            txn = Transaction.objects.get(id=transaction_id)
        except Transaction.DoesNotExist:
            raise BankingException("Transaction not found.")

        # Ensure claimant was the sender
        if txn.sender_wallet and txn.sender_wallet.user_id != user.id:
            raise PermissionDenied("You can only dispute transactions originated from your wallet.")

        if txn.status not in [TransactionStatus.COMPLETED, TransactionStatus.PARTIALLY_REFUNDED]:
            raise BankingException("Only completed transactions can be disputed.")

        if TransactionDispute.objects.filter(transaction=txn, status__in=[DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW]).exists():
            raise BankingException("An active dispute is already open for this transaction.")

        dispute = TransactionDispute.objects.create(
            transaction=txn,
            claimant=user,
            dispute_type=dispute_type,
            reason=reason,
            evidence_file=evidence_file,
            status=DisputeStatus.OPEN
        )

        AuditLog.objects.create(
            user=user,
            action="DISPUTE_FILED",
            entity_type="TransactionDispute",
            entity_id=str(dispute.id),
            new_value={"dispute_code": dispute.dispute_code, "type": dispute_type}
        )
        return dispute

    @classmethod
    def resolve_dispute(
        cls,
        reviewer_user: User,
        dispute_id: str,
        decision: str,
        resolution_notes: str
    ) -> TransactionDispute:
        if not reviewer_user.is_admin_or_staff:
            raise PermissionDenied("Compliance or Admin privileges are required to resolve disputes.")

        try:
            dispute = TransactionDispute.objects.select_related("transaction", "claimant").get(id=dispute_id)
        except TransactionDispute.DoesNotExist:
            raise BankingException("Dispute record not found.")

        if dispute.status in [DisputeStatus.ACCEPTED, DisputeStatus.REJECTED]:
            raise BankingException(f"Dispute has already been resolved as {dispute.status}.")

        with transaction.atomic():
            if decision == DisputeStatus.ACCEPTED:
                # Issue refund to claimant
                RefundService.process_refund(
                    initiator_user=reviewer_user,
                    original_transaction_id=str(dispute.transaction_id),
                    amount=dispute.transaction.amount,
                    reason=f"Dispute {dispute.dispute_code} accepted: {resolution_notes}"
                )
                dispute.status = DisputeStatus.ACCEPTED
            elif decision == DisputeStatus.REJECTED:
                dispute.status = DisputeStatus.REJECTED
            else:
                raise BankingException("Decision must be either ACCEPTED or REJECTED.")

            dispute.reviewer = reviewer_user
            dispute.resolution_notes = resolution_notes
            dispute.resolved_at = timezone.now()
            dispute.save(update_fields=["status", "reviewer", "resolution_notes", "resolved_at", "updated_at"])

            AuditLog.objects.create(
                user=reviewer_user,
                action="DISPUTE_RESOLVED",
                entity_type="TransactionDispute",
                entity_id=str(dispute.id),
                new_value={"decision": dispute.status, "notes": resolution_notes}
            )

        return dispute
