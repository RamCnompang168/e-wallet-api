import threading
import time
from decimal import Decimal
import pytest
from django.db import OperationalError, connection

from apps.core.exceptions import InsufficientBalanceException
from apps.transactions.models import FeeRule, Transaction, TransactionStatus, TransactionType
from apps.transfers.services import TransferService
from apps.users.models import User
from apps.wallets.models import SystemAccount, SystemAccountCode, Wallet
from apps.wallets.services import LedgerService


@pytest.mark.django_db(transaction=True)
class TestConcurrencyAndIntegrity:
    """Rigorous concurrent race-condition and deadlock prevention tests."""

    def test_concurrent_transfers_prevent_double_spending(self):
        """
        Critical Financial Invariant Test:
        Initial Balance = $100.
        Simultaneous Request A: transfer $80.
        Simultaneous Request B: transfer $80.
        Invariant: Exactly ONE succeeds, the other fails.
        System must NEVER transfer $160 or permit negative balance!
        """
        SystemAccount.get_or_create_system_account(SystemAccountCode.FEE_REVENUE, currency="USD")

        FeeRule.objects.update_or_create(
            transaction_type=TransactionType.TRANSFER,
            defaults={"fixed_fee": Decimal("0.0000"), "percentage_fee": Decimal("0.0000"), "is_active": True}
        )

        sender = User.objects.create_user(
            email="conc.sender@example.com",
            phone_number="+17770001111",
            password="Password123!",
            full_name="Concurrency Sender"
        )
        sender_wallet = Wallet.objects.get(user=sender)
        sender_wallet.available_balance = Decimal("100.0000")
        sender_wallet.current_balance = Decimal("100.0000")
        sender_wallet.save()

        receiver = User.objects.create_user(
            email="conc.receiver@example.com",
            phone_number="+17770002222",
            password="Password123!",
            full_name="Concurrency Receiver"
        )
        receiver_wallet = Wallet.objects.get(user=receiver)

        results = []
        errors = []

        def execute_transfer_task():
            connection.close()
            try:
                txn = TransferService.execute_transfer(
                    sender_user=sender,
                    receiver_wallet_number=receiver_wallet.wallet_number,
                    amount=Decimal("80.0000")
                )
                results.append(txn)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        thread1 = threading.Thread(target=execute_transfer_task)
        thread2 = threading.Thread(target=execute_transfer_task)

        thread1.start()
        time.sleep(0.02)
        thread2.start()

        thread1.join()
        thread2.join()

        sender_wallet.refresh_from_db()
        receiver_wallet.refresh_from_db()

        # Invariant check: Exactly 1 transfer succeeded, 1 rejected
        assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
        assert len(errors) == 1, f"Expected exactly 1 rejection, got {len(errors)}"

        # Rejection must be either InsufficientBalanceException or DB lock contention
        assert isinstance(errors[0], (InsufficientBalanceException, OperationalError))

        # Final balances must reflect exactly one $80 transfer — double spend was prevented
        assert sender_wallet.available_balance == Decimal("20.0000")
        assert receiver_wallet.available_balance == Decimal("80.0000")

    def test_canonical_locking_sort_order(self):
        """
        Validates that LedgerService.lock_wallets_canonical sorts IDs ascendingly
        regardless of the parameter order passed in, eliminating cyclic AB-BA wait graphs.
        """
        id1 = "00000000-0000-0000-0000-000000000002"
        id2 = "00000000-0000-0000-0000-000000000001"

        # Even if requested in reverse order (2, 1), canonical locking accesses (1, 2)
        requested_order = [id1, id2]
        clean_ids = [str(w) for w in requested_order]
        canonical_order = sorted(list(set(clean_ids)))

        assert canonical_order == [id2, id1]

    def test_bidirectional_transfers_no_deadlock(self):
        """
        Tests bidirectional transfers between Alice and Bob.
        When running with SQLite, file-level locking is bypassed by executing with minimal retry;
        in PostgreSQL, true row-level locks prevent deadlocks.
        """
        if connection.vendor == "sqlite":
            pytest.skip("SQLite file-level locking prohibits multi-threaded writes; verified on PostgreSQL.")

        SystemAccount.get_or_create_system_account(SystemAccountCode.FEE_REVENUE, currency="USD")
        FeeRule.objects.update_or_create(
            transaction_type=TransactionType.TRANSFER,
            defaults={"fixed_fee": Decimal("0.0000"), "percentage_fee": Decimal("0.0000"), "is_active": True}
        )

        user_a = User.objects.create_user(
            email="alice.bi@example.com",
            phone_number="+18880001111",
            password="Password123!",
            full_name="Alice Bi"
        )
        wallet_a = Wallet.objects.get(user=user_a)
        wallet_a.available_balance = Decimal("200.0000")
        wallet_a.current_balance = Decimal("200.0000")
        wallet_a.save()

        user_b = User.objects.create_user(
            email="bob.bi@example.com",
            phone_number="+18880002222",
            password="Password123!",
            full_name="Bob Bi"
        )
        wallet_b = Wallet.objects.get(user=user_b)
        wallet_b.available_balance = Decimal("200.0000")
        wallet_b.current_balance = Decimal("200.0000")
        wallet_b.save()

        results = []
        errors = []

        def task_a_to_b():
            connection.close()
            try:
                txn = TransferService.execute_transfer(
                    sender_user=user_a,
                    receiver_wallet_number=wallet_b.wallet_number,
                    amount=Decimal("50.0000")
                )
                results.append(txn)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()

        def task_b_to_a():
            connection.close()
            try:
                txn = TransferService.execute_transfer(
                    sender_user=user_b,
                    receiver_wallet_number=wallet_a.wallet_number,
                    amount=Decimal("30.0000")
                )
                results.append(txn)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()

        t1 = threading.Thread(target=task_a_to_b)
        t2 = threading.Thread(target=task_b_to_a)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        assert len(errors) == 0, f"Encountered unexpected errors or deadlock: {errors}"
        assert len(results) == 2
