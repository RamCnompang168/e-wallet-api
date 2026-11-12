import logging
from typing import Optional
from django.utils import timezone

from apps.notifications.models import Notification, NotificationType
from apps.transactions.models import Transaction
from apps.users.models import User

logger = logging.getLogger("banking.notifications")


class NotificationService:
    """Manages creation, dispatching, and reading of user notifications."""

    @classmethod
    def create_notification(
        cls,
        user: User,
        title: str,
        message: str,
        notification_type: str = NotificationType.TRANSACTION,
        related_transaction: Optional[Transaction] = None
    ) -> Notification:
        notification = Notification.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            related_transaction=related_transaction
        )

        # Dispatch async task if worker is enabled
        try:
            from apps.notifications.tasks import send_notification_email_task
            send_notification_email_task.delay(user.email, title, message)
        except Exception:
            # Safe local fallback
            logger.info("Notification stored: %s - %s", user.email, title)

        return notification

    @classmethod
    def notify_transfer_parties(cls, txn: Transaction) -> None:
        """Notifies both sender and receiver upon successful transfer."""
        if txn.sender_wallet and txn.sender_wallet.user:
            receiver_name = (
                txn.receiver_wallet.user.full_name
                if txn.receiver_wallet and txn.receiver_wallet.user
                else (
                    (txn.metadata or {}).get("payee_name")
                    or (txn.metadata or {}).get("external_account")
                    or (txn.receiver_wallet.wallet_number if txn.receiver_wallet else "Recipient")
                )
            )
            cls.create_notification(
                user=txn.sender_wallet.user,
                title="Transfer Sent Successfully",
                message=f"You transferred ${txn.amount:.2f} {txn.currency} to {receiver_name}. Fee: ${txn.fee_amount:.2f}. Reference: {txn.transaction_code}.",
                notification_type=NotificationType.TRANSACTION,
                related_transaction=txn
            )

        if txn.receiver_wallet and txn.receiver_wallet.user:
            sender_name = (
                txn.sender_wallet.user.full_name
                if txn.sender_wallet and txn.sender_wallet.user
                else (txn.sender_wallet.wallet_number if txn.sender_wallet else "System")
            )
            cls.create_notification(
                user=txn.receiver_wallet.user,
                title="Money Received",
                message=f"You received ${txn.amount:.2f} {txn.currency} from {sender_name}. Reference: {txn.transaction_code}.",
                notification_type=NotificationType.TRANSACTION,
                related_transaction=txn
            )

    @classmethod
    def notify_topup(cls, txn: Transaction, user: User, payment_method_name: str = "") -> None:
        """Notifies user upon successful wallet deposit/top-up."""
        method_str = f" via {payment_method_name}" if payment_method_name else ""
        cls.create_notification(
            user=user,
            title="Deposit Confirmed",
            message=f"Successfully deposited ${txn.amount:.2f} {txn.currency} into your wallet{method_str}. Reference: {txn.transaction_code}.",
            notification_type=NotificationType.TRANSACTION,
            related_transaction=txn
        )

    @classmethod
    def notify_withdrawal(cls, txn: Transaction, user: User, destination_account: str = "") -> None:
        """Notifies user upon successful fund withdrawal."""
        dest_str = f" to {destination_account}" if destination_account else ""
        cls.create_notification(
            user=user,
            title="Withdrawal Completed",
            message=f"Withdrew ${txn.amount:.2f} {txn.currency}{dest_str}. Fee: ${txn.fee_amount:.2f}. Reference: {txn.transaction_code}.",
            notification_type=NotificationType.TRANSACTION,
            related_transaction=txn
        )

    @classmethod
    def notify_kyc_result(cls, verification, decision: str, reason: str = "") -> None:
        """Notifies applicant upon compliance decision."""
        if decision == "APPROVED":
            title = "KYC Verification Approved"
            msg = f"Congratulations! Your account has been upgraded to KYC Tier {verification.target_tier}."
        else:
            title = "KYC Verification Rejected"
            msg = f"Your KYC application was not approved. Reason: {reason}."

        cls.create_notification(
            user=verification.user,
            title=title,
            message=msg,
            notification_type=NotificationType.KYC
        )
