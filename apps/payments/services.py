import logging
import secrets
from decimal import Decimal
from typing import Optional
from django.db import transaction

from apps.core.exceptions import (
    BankingException,
    InsufficientBalanceException,
    KYCRequiredException,
    LimitExceededException,
    WalletInactiveException,
)
from apps.payments.models import (
    PaymentMethod,
    TopUp,
    TopUpStatus,
    Withdrawal,
    WithdrawalStatus,
)
from apps.transactions.models import FeeRule, Transaction, TransactionLimit, TransactionStatus, TransactionType
from apps.users.models import AuditLog, User
from apps.wallets.models import Wallet
from apps.wallets.services import LedgerService

logger = logging.getLogger("banking.payments")


class TopUpService:
    """Manages inbound wallet funding operations."""

    @classmethod
    def execute_topup(
        cls,
        user: User,
        payment_method_id: str,
        amount: Decimal,
        provider_reference: Optional[str] = None
    ) -> Transaction:
        if amount <= Decimal("0.0000"):
            raise BankingException("Top-up amount must be strictly positive.")

        payment_method = PaymentMethod.objects.filter(id=payment_method_id, is_active=True).first()
        if not payment_method:
            raise BankingException("Invalid or inactive payment method selected.")

        wallet = Wallet.objects.filter(user=user, is_primary=True, status="ACTIVE").first()
        if not wallet:
            raise WalletInactiveException("No active primary wallet found.")

        # Calculate fee
        rule = FeeRule.objects.filter(transaction_type=TransactionType.TOPUP, is_active=True).first()
        fee_amount = rule.calculate_fee(amount) if rule else Decimal("0.0000")

        ref = provider_reference or f"SIM-PAY-{secrets.token_hex(6).upper()}"

        with transaction.atomic():
            # Lock wallet
            locked = LedgerService.lock_wallets_canonical(wallet.id)
            locked_wallet = locked[str(wallet.id)]

            txn = Transaction.objects.create(
                transaction_type=TransactionType.TOPUP,
                status=TransactionStatus.PROCESSING,
                receiver_wallet=locked_wallet,
                amount=amount,
                fee_amount=fee_amount,
                total_amount=amount,
                currency=locked_wallet.currency,
                description=f"Top-up via {payment_method.method_name}",
                reference_number=ref,
            )

            # Record double-entry ledger entries
            LedgerService.post_topup_entries(
                txn=txn,
                receiver_wallet=locked_wallet,
                amount=amount,
                fee_amount=fee_amount
            )

            topup_record = TopUp.objects.create(
                transaction=txn,
                payment_method=payment_method,
                provider_reference=ref,
                amount=amount,
                fee_amount=fee_amount,
                status=TopUpStatus.COMPLETED
            )

            txn.transition_to(TransactionStatus.COMPLETED)
            txn.save(update_fields=["status", "completed_at", "updated_at"])

            AuditLog.objects.create(
                user=user,
                action="TOPUP_COMPLETED",
                entity_type="Transaction",
                entity_id=str(txn.id),
                new_value={"amount": str(amount), "fee": str(fee_amount), "provider": payment_method.provider_name}
            )

            transaction.on_commit(
                lambda: cls._dispatch_topup_notification(txn, user, payment_method.method_name)
            )

        return txn

    @staticmethod
    def _dispatch_topup_notification(txn: Transaction, user: User, method_name: str) -> None:
        try:
            from apps.notifications.services import NotificationService
            NotificationService.notify_topup(txn, user, method_name)
        except Exception as e:
            logger.error("Failed to dispatch topup notification: %s", e)


class WithdrawalService:
    """Manages outbound fund withdrawals with balance holds and ledger execution."""

    @classmethod
    def execute_withdrawal(
        cls,
        user: User,
        payment_method_id: str,
        destination_account: str,
        amount: Decimal,
        pin: Optional[str] = None
    ) -> Transaction:
        if amount <= Decimal("0.0000"):
            raise BankingException("Withdrawal amount must be strictly positive.")

        # Require KYC Tier 1+ for outbound withdrawals
        if user.kyc_tier < 1:
            raise KYCRequiredException(
                "Identity verification (KYC Tier 1) is strictly required to withdraw funds."
            )

        # Verify PIN
        if user.pin_hash:
            if not pin:
                raise BankingException("Transaction PIN is required to authorize withdrawal.")
            user.verify_pin(pin)

        payment_method = PaymentMethod.objects.filter(id=payment_method_id, is_active=True).first()
        if not payment_method:
            raise BankingException("Invalid or inactive withdrawal rail.")

        wallet = Wallet.objects.filter(user=user, is_primary=True, status="ACTIVE").first()
        if not wallet:
            raise WalletInactiveException("No active primary wallet found.")

        # Calculate fee
        rule = FeeRule.objects.filter(transaction_type=TransactionType.WITHDRAWAL, is_active=True).first()
        fee_amount = rule.calculate_fee(amount) if rule else Decimal("0.0000")
        total_debit = amount + fee_amount

        ref = f"WD-{secrets.token_hex(6).upper()}"

        with transaction.atomic():
            locked = LedgerService.lock_wallets_canonical(wallet.id)
            locked_wallet = locked[str(wallet.id)]

            if locked_wallet.available_balance < total_debit:
                raise InsufficientBalanceException("Available wallet balance is insufficient for withdrawal.")

            txn = Transaction.objects.create(
                transaction_type=TransactionType.WITHDRAWAL,
                status=TransactionStatus.PROCESSING,
                sender_wallet=locked_wallet,
                amount=amount,
                fee_amount=fee_amount,
                total_amount=total_debit,
                currency=locked_wallet.currency,
                description=f"Withdrawal to {destination_account} ({payment_method.method_name})",
                reference_number=ref,
            )

            LedgerService.post_withdrawal_entries(
                txn=txn,
                sender_wallet=locked_wallet,
                amount=amount,
                fee_amount=fee_amount
            )

            Withdrawal.objects.create(
                transaction=txn,
                payment_method=payment_method,
                destination_account=destination_account,
                provider_reference=ref,
                amount=amount,
                fee_amount=fee_amount,
                status=WithdrawalStatus.COMPLETED
            )

            txn.transition_to(TransactionStatus.COMPLETED)
            txn.save(update_fields=["status", "completed_at", "updated_at"])

            AuditLog.objects.create(
                user=user,
                action="WITHDRAWAL_COMPLETED",
                entity_type="Transaction",
                entity_id=str(txn.id),
                new_value={"amount": str(amount), "fee": str(fee_amount), "destination": destination_account}
            )

            transaction.on_commit(
                lambda: cls._dispatch_withdrawal_notification(txn, user, destination_account)
            )

        return txn

    @staticmethod
    def _dispatch_withdrawal_notification(txn: Transaction, user: User, destination_account: str) -> None:
        try:
            from apps.notifications.services import NotificationService
            NotificationService.notify_withdrawal(txn, user, destination_account)
        except Exception as e:
            logger.error("Failed to dispatch withdrawal notification: %s", e)


class KhqrService:
    """Manages live Bakong KHQR code generation and verification via KHQR.dev."""

    @classmethod
    def get_token(cls) -> str:
        import os
        from django.conf import settings
        return (
            os.environ.get("KHQR_RBK_TOKEN")
            or os.environ.get("RBK_TOKEN")
            or getattr(settings, "KHQR_RBK_TOKEN", None)
            or getattr(settings, "RBK_TOKEN", "rbk_W0Tsm02sxPXAWlu1CqYjKT20ClAMCdqX")
        )

    @classmethod
    def generate_qr(cls, amount: float | Decimal) -> dict:
        import json
        import urllib.request
        import urllib.error

        token = cls.get_token()
        amt = float(amount)
        if amt < 0.01:
            amt = 0.01

        url = "https://api.khqr.dev/v1/generate_qr"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }
        data = json.dumps({"amount": round(amt, 2)}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                data_obj = result.get("data", {})
                md5 = data_obj.get("md5", "")
                data_obj["qr_image_url"] = f"https://api.khqr.dev/v1/generate_khqr_image/{md5}"
                return data_obj
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            logger.error("KHQR generate_qr HTTP %s: %s", e.code, err_body)
            raise BankingException(f"Failed to generate live KHQR: {err_body}")
        except Exception as e:
            logger.error("KHQR generate_qr error: %s", e)
            raise BankingException(f"Failed to connect to KHQR gateway: {str(e)}")

    @classmethod
    def check_transaction(cls, md5: str) -> dict:
        import json
        import urllib.request
        import urllib.error

        token = cls.get_token()
        url = "https://api.khqr.dev/v1/check_transaction_by_md5"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }
        data = json.dumps({"md5": md5.strip()}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                return result.get("data", {})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                try:
                    res = json.loads(e.read().decode("utf-8"))
                    return res.get("data", {"status": "unpaid"})
                except Exception:
                    return {"status": "unpaid"}
            err_body = e.read().decode("utf-8")
            logger.error("KHQR check_transaction HTTP %s: %s", e.code, err_body)
            return {"status": "unpaid", "error": err_body}
        except Exception as e:
            logger.error("KHQR check_transaction error: %s", e)
            return {"status": "unpaid", "error": str(e)}

    @classmethod
    def fulfill_payment_if_paid(cls, user: Optional[User], md5: str, amount: Decimal) -> tuple[bool, Optional[Transaction]]:
        data = cls.check_transaction(md5)
        status_val = data.get("status", "").lower()

        if status_val == "paid":
            tran_id = str(data.get("tran_id") or md5)
            # Idempotency check: prevent double crediting
            existing = TopUp.objects.filter(provider_reference=f"KHQR-{md5}").first()
            if existing:
                return True, existing.transaction

            # If user is anonymous or None, resolve the primary active user
            if not user or not getattr(user, "is_authenticated", False):
                user = User.objects.filter(is_active=True).first()

            if not user:
                return True, None

            method = PaymentMethod.objects.filter(is_active=True, method_type="DIGITAL_WALLET").first()
            if not method:
                method = PaymentMethod.objects.filter(is_active=True).first()

            txn = TopUpService.execute_topup(
                user=user,
                payment_method_id=str(method.id),
                amount=amount,
                provider_reference=f"KHQR-{md5}",
            )
            return True, txn

        return False, None
