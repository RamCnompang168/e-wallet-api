import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union
from django.db import transaction
from django.db.models import F

from apps.core.exceptions import (
    CurrencyMismatchException,
    InsufficientBalanceException,
    LedgerImbalanceException,
    WalletInactiveException,
)
from apps.wallets.models import (
    LedgerEntry,
    LedgerEntryType,
    SystemAccount,
    SystemAccountCode,
    Wallet,
    WalletStatus,
)

logger = logging.getLogger("banking.ledger")


class LedgerService:
    """
    Core double-entry financial ledger engine.
    Guarantees that every monetary transaction preserves:
        Total Debit == Total Credit
    and updates cached wallet balances atomically.
    """

    @classmethod
    def lock_wallets_canonical(cls, *wallet_ids: Union[str, Wallet]) -> Dict[str, Wallet]:
        """
        Pessimistically locks wallets in strict ascending primary key order to prevent deadlocks.
        Always call this inside an active transaction.atomic() block.
        """
        clean_ids = [str(w.id) if isinstance(w, Wallet) else str(w) for w in wallet_ids if w is not None]
        unique_sorted_ids = sorted(list(set(clean_ids)))

        if not unique_sorted_ids:
            return {}

        # Query and lock in ascending primary key order
        wallets = list(Wallet.objects.select_for_update().filter(id__in=unique_sorted_ids))
        locked_map = {str(w.id): w for w in wallets}

        for wid in unique_sorted_ids:
            if wid not in locked_map:
                raise WalletInactiveException(f"Wallet {wid} could not be located for settlement.")

        return locked_map

    @classmethod
    def post_transfer_entries(
        cls,
        txn,
        sender_wallet: Wallet,
        receiver_wallet: Wallet,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0.0000")
    ) -> List[LedgerEntry]:
        """
        Generates balanced double-entry records for a P2P transfer:
        1. DEBIT Sender Wallet: (Amount + Fee)
        2. CREDIT Receiver Wallet: Amount
        3. CREDIT System Fee Account: Fee (if fee > 0)
        Invariant: Total Debits == Total Credits.
        """
        total_debit = amount + fee_amount

        # Validate currency consistency
        if sender_wallet.currency != txn.currency or receiver_wallet.currency != txn.currency:
            raise CurrencyMismatchException("Currency mismatch between wallets and transaction denomination.")

        # Validate wallet operational statuses
        if not sender_wallet.is_active:
            raise WalletInactiveException(f"Sender wallet {sender_wallet.wallet_number} is not active.")
        if not receiver_wallet.is_active:
            raise WalletInactiveException(f"Receiver wallet {receiver_wallet.wallet_number} is not active.")

        # Check sufficient funds
        if sender_wallet.available_balance < total_debit:
            raise InsufficientBalanceException(
                f"Available balance ({sender_wallet.available_balance} {sender_wallet.currency}) "
                f"is insufficient for transfer of {total_debit} {sender_wallet.currency}."
            )

        entries = []

        # 1. DEBIT Sender Wallet
        sender_before = sender_wallet.available_balance
        sender_wallet.available_balance -= total_debit
        sender_wallet.current_balance -= total_debit
        sender_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        sender_entry = LedgerEntry.objects.create(
            transaction=txn,
            wallet=sender_wallet,
            entry_type=LedgerEntryType.DEBIT,
            amount=total_debit,
            balance_before=sender_before,
            balance_after=sender_wallet.available_balance,
            description=f"Transfer to {receiver_wallet.wallet_number}" + (f" (incl. {fee_amount} fee)" if fee_amount > 0 else "")
        )
        entries.append(sender_entry)

        # 2. CREDIT Receiver Wallet
        receiver_before = receiver_wallet.available_balance
        receiver_wallet.available_balance += amount
        receiver_wallet.current_balance += amount
        receiver_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        receiver_entry = LedgerEntry.objects.create(
            transaction=txn,
            wallet=receiver_wallet,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            balance_before=receiver_before,
            balance_after=receiver_wallet.available_balance,
            description=f"Transfer received from {sender_wallet.wallet_number}"
        )
        entries.append(receiver_entry)

        # 3. CREDIT System Fee Account (if fee applied)
        if fee_amount > Decimal("0.0000"):
            fee_account = SystemAccount.get_or_create_system_account(
                code=SystemAccountCode.FEE_REVENUE,
                currency=txn.currency
            )
            fee_before = fee_account.balance
            fee_account.balance += fee_amount
            fee_account.save(update_fields=["balance", "updated_at"])

            fee_entry = LedgerEntry.objects.create(
                transaction=txn,
                system_account=fee_account,
                entry_type=LedgerEntryType.CREDIT,
                amount=fee_amount,
                balance_before=fee_before,
                balance_after=fee_account.balance,
                description=f"Fee for txn {txn.transaction_code}"
            )
            entries.append(fee_entry)

        # Invariant Verification
        total_debits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.DEBIT)
        total_credits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.CREDIT)

        if total_debits != total_credits:
            raise LedgerImbalanceException(
                f"Double-entry ledger imbalance! Debits={total_debits}, Credits={total_credits}"
            )

        logger.info(
            "Settled transfer %s: Debited %s from %s, Credited %s to %s",
            txn.transaction_code, total_debit, sender_wallet.wallet_number, amount, receiver_wallet.wallet_number
        )
        return entries

    @classmethod
    def post_topup_entries(
        cls,
        txn,
        receiver_wallet: Wallet,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0.0000")
    ) -> List[LedgerEntry]:
        """
        Balances inbound Top-Up:
        1. DEBIT System External Clearing: Amount
        2. CREDIT Receiver Wallet: (Amount - Fee)
        3. CREDIT System Fee: Fee
        """
        if not receiver_wallet.is_active:
            raise WalletInactiveException("Wallet is not active.")

        net_credit = amount - fee_amount
        if net_credit <= Decimal("0.0000"):
            raise InsufficientBalanceException("Top-up amount must exceed applicable fees.")

        clearing_account = SystemAccount.get_or_create_system_account(
            code=SystemAccountCode.EXTERNAL_CLEARING,
            currency=txn.currency
        )

        entries = []

        # 1. DEBIT Clearing
        clearing_before = clearing_account.balance
        clearing_account.balance -= amount
        clearing_account.save(update_fields=["balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            system_account=clearing_account,
            entry_type=LedgerEntryType.DEBIT,
            amount=amount,
            balance_before=clearing_before,
            balance_after=clearing_account.balance,
            description=f"External top-up clearing for {receiver_wallet.wallet_number}"
        ))

        # 2. CREDIT Receiver Wallet
        rec_before = receiver_wallet.available_balance
        receiver_wallet.available_balance += net_credit
        receiver_wallet.current_balance += net_credit
        receiver_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            wallet=receiver_wallet,
            entry_type=LedgerEntryType.CREDIT,
            amount=net_credit,
            balance_before=rec_before,
            balance_after=receiver_wallet.available_balance,
            description=f"Wallet top-up via external gateway"
        ))

        # 3. CREDIT Fee Account if fee > 0
        if fee_amount > Decimal("0.0000"):
            fee_account = SystemAccount.get_or_create_system_account(
                code=SystemAccountCode.FEE_REVENUE,
                currency=txn.currency
            )
            fee_before = fee_account.balance
            fee_account.balance += fee_amount
            fee_account.save(update_fields=["balance", "updated_at"])

            entries.append(LedgerEntry.objects.create(
                transaction=txn,
                system_account=fee_account,
                entry_type=LedgerEntryType.CREDIT,
                amount=fee_amount,
                balance_before=fee_before,
                balance_after=fee_account.balance,
                description=f"Fee on top-up {txn.transaction_code}"
            ))

        return entries

    @classmethod
    def post_withdrawal_entries(
        cls,
        txn,
        sender_wallet: Wallet,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0.0000")
    ) -> List[LedgerEntry]:
        """
        Balances outbound Withdrawal:
        1. DEBIT Sender Wallet: (Amount + Fee)
        2. CREDIT System External Clearing: Amount
        3. CREDIT System Fee Account: Fee
        """
        total_debit = amount + fee_amount

        if not sender_wallet.is_active:
            raise WalletInactiveException("Wallet is not active.")
        if sender_wallet.available_balance < total_debit:
            raise InsufficientBalanceException("Available balance is insufficient for withdrawal.")

        clearing_account = SystemAccount.get_or_create_system_account(
            code=SystemAccountCode.EXTERNAL_CLEARING,
            currency=txn.currency
        )

        entries = []

        # 1. DEBIT Sender Wallet
        sender_before = sender_wallet.available_balance
        sender_wallet.available_balance -= total_debit
        sender_wallet.current_balance -= total_debit
        sender_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            wallet=sender_wallet,
            entry_type=LedgerEntryType.DEBIT,
            amount=total_debit,
            balance_before=sender_before,
            balance_after=sender_wallet.available_balance,
            description=f"Withdrawal to external account"
        ))

        # 2. CREDIT Clearing
        clearing_before = clearing_account.balance
        clearing_account.balance += amount
        clearing_account.save(update_fields=["balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            system_account=clearing_account,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            balance_before=clearing_before,
            balance_after=clearing_account.balance,
            description=f"Withdrawal payout clearing"
        ))

        # 3. CREDIT Fee Account
        if fee_amount > Decimal("0.0000"):
            fee_account = SystemAccount.get_or_create_system_account(
                code=SystemAccountCode.FEE_REVENUE,
                currency=txn.currency
            )
            fee_before = fee_account.balance
            fee_account.balance += fee_amount
            fee_account.save(update_fields=["balance", "updated_at"])

            entries.append(LedgerEntry.objects.create(
                transaction=txn,
                system_account=fee_account,
                entry_type=LedgerEntryType.CREDIT,
                amount=fee_amount,
                balance_before=fee_before,
                balance_after=fee_account.balance,
                description=f"Withdrawal fee {txn.transaction_code}"
            ))

        return entries

    @classmethod
    def post_external_payment_entries(
        cls,
        txn,
        sender_wallet: Wallet,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0.0000"),
        channel: str = "Bakong KHQR",
    ) -> List[LedgerEntry]:
        """
        Balances outbound external payment / KHQR transfer:
        1. DEBIT Sender Wallet: (Amount + Fee)
        2. CREDIT System External Clearing: Amount
        3. CREDIT System Fee Account: Fee (if fee > 0)
        """
        total_debit = amount + fee_amount

        if not sender_wallet.is_active:
            raise WalletInactiveException("Sender wallet is not active.")
        if sender_wallet.available_balance < total_debit:
            raise InsufficientBalanceException("Available balance is insufficient for external payment.")

        clearing_account = SystemAccount.get_or_create_system_account(
            code=SystemAccountCode.EXTERNAL_CLEARING,
            currency=txn.currency
        )

        entries = []

        # 1. DEBIT Sender Wallet
        sender_before = sender_wallet.available_balance
        sender_wallet.available_balance -= total_debit
        sender_wallet.current_balance -= total_debit
        sender_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            wallet=sender_wallet,
            entry_type=LedgerEntryType.DEBIT,
            amount=total_debit,
            balance_before=sender_before,
            balance_after=sender_wallet.available_balance,
            description=f"Outbound {channel} transfer"
        ))

        # 2. CREDIT Clearing
        clearing_before = clearing_account.balance
        clearing_account.balance += amount
        clearing_account.save(update_fields=["balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            system_account=clearing_account,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            balance_before=clearing_before,
            balance_after=clearing_account.balance,
            description=f"{channel} settlement clearing"
        ))

        # 3. CREDIT Fee Account if fee > 0
        if fee_amount > Decimal("0.0000"):
            fee_account = SystemAccount.get_or_create_system_account(
                code=SystemAccountCode.FEE_REVENUE,
                currency=txn.currency
            )
            fee_before = fee_account.balance
            fee_account.balance += fee_amount
            fee_account.save(update_fields=["balance", "updated_at"])

            entries.append(LedgerEntry.objects.create(
                transaction=txn,
                system_account=fee_account,
                entry_type=LedgerEntryType.CREDIT,
                amount=fee_amount,
                balance_before=fee_before,
                balance_after=fee_account.balance,
                description=f"Fee on {channel} transfer {txn.transaction_code}"
            ))

        return entries

    @classmethod
    def post_refund_entries(
        cls,
        txn,
        debtor_wallet: Wallet,
        creditor_wallet: Wallet,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0.0000")
    ) -> List[LedgerEntry]:
        """
        Balances full or partial refund:
        1. DEBIT Debtor Wallet (Merchant): (Amount - Fee)
        2. DEBIT System Fee Revenue Account: Fee (reversing the collected platform fee)
        3. CREDIT Creditor Wallet (Customer): Amount
        Invariant: Total Debits == Total Credits == Amount.
        """
        net_debtor_debit = amount - fee_amount
        if debtor_wallet.available_balance < net_debtor_debit:
            raise InsufficientBalanceException(
                f"Wallet issuing refund has insufficient funds ({debtor_wallet.available_balance} < {net_debtor_debit})."
            )

        entries = []

        # 1. DEBIT Debtor Wallet
        debtor_before = debtor_wallet.available_balance
        debtor_wallet.available_balance -= net_debtor_debit
        debtor_wallet.current_balance -= net_debtor_debit
        debtor_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            wallet=debtor_wallet,
            entry_type=LedgerEntryType.DEBIT,
            amount=net_debtor_debit,
            balance_before=debtor_before,
            balance_after=debtor_wallet.available_balance,
            description=f"Refund issued to {creditor_wallet.wallet_number}"
        ))

        # 2. DEBIT System Fee Revenue (if fee reversed)
        if fee_amount > Decimal("0.0000"):
            fee_account = SystemAccount.get_or_create_system_account(
                code=SystemAccountCode.FEE_REVENUE,
                currency=txn.currency
            )
            fee_before = fee_account.balance
            fee_account.balance -= fee_amount
            fee_account.save(update_fields=["balance", "updated_at"])

            entries.append(LedgerEntry.objects.create(
                transaction=txn,
                system_account=fee_account,
                entry_type=LedgerEntryType.DEBIT,
                amount=fee_amount,
                balance_before=fee_before,
                balance_after=fee_account.balance,
                description=f"Fee reversal on refund {txn.transaction_code}"
            ))

        # 3. CREDIT Creditor Wallet (Customer receiving refund)
        creditor_before = creditor_wallet.available_balance
        creditor_wallet.available_balance += amount
        creditor_wallet.current_balance += amount
        creditor_wallet.save(update_fields=["available_balance", "current_balance", "updated_at"])

        entries.append(LedgerEntry.objects.create(
            transaction=txn,
            wallet=creditor_wallet,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            balance_before=creditor_before,
            balance_after=creditor_wallet.available_balance,
            description=f"Refund received from {debtor_wallet.wallet_number}"
        ))

        return entries

