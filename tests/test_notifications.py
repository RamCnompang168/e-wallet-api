from decimal import Decimal
import pytest
from rest_framework.test import APIClient

from apps.notifications.models import Notification, NotificationType
from apps.payments.models import PaymentMethod, PaymentMethodType
from apps.payments.services import TopUpService, WithdrawalService
from apps.transfers.services import TransferService
from apps.users.models import User
from apps.wallets.models import SystemAccount, SystemAccountCode, Wallet


@pytest.mark.django_db(transaction=True)
class TestNotificationFlow:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        SystemAccount.get_or_create_system_account(SystemAccountCode.EXTERNAL_CLEARING, currency="USD")
        SystemAccount.get_or_create_system_account(SystemAccountCode.FEE_REVENUE, currency="USD")

        self.payment_method = PaymentMethod.objects.create(
            method_name="Direct Bank Debit",
            method_type=PaymentMethodType.BANK_TRANSFER,
            provider_name="TestBankProvider",
            is_active=True
        )

        self.sender = User.objects.create_user(
            email="notif_sender@novapay.bank",
            phone_number="+85512349001",
            password="Password123!",
            full_name="Sender Chan",
            kyc_tier=1
        )
        self.sender.set_pin("123456")
        self.sender.save()

        self.sender_wallet = Wallet.objects.get(user=self.sender)
        self.sender_wallet.available_balance = Decimal("500.0000")
        self.sender_wallet.current_balance = Decimal("500.0000")
        self.sender_wallet.save()

        self.receiver = User.objects.create_user(
            email="notif_receiver@novapay.bank",
            phone_number="+85512349002",
            password="Password123!",
            full_name="Receiver Meas",
            kyc_tier=1
        )
        self.receiver.set_pin("123456")
        self.receiver.save()

        self.receiver_wallet = Wallet.objects.get(user=self.receiver)
        self.receiver_wallet.available_balance = Decimal("100.0000")
        self.receiver_wallet.current_balance = Decimal("100.0000")
        self.receiver_wallet.save()

        self.client = APIClient()

    def test_deposit_generates_notification(self):
        txn = TopUpService.execute_topup(
            user=self.sender,
            payment_method_id=str(self.payment_method.id),
            amount=Decimal("75.0000")
        )
        notif = Notification.objects.filter(
            user=self.sender,
            notification_type=NotificationType.TRANSACTION,
            title="Deposit Confirmed"
        ).first()

        assert notif is not None
        assert "75.00 USD" in notif.message
        assert txn.transaction_code in notif.message
        assert notif.is_read is False

    def test_withdrawal_generates_notification(self):
        txn = WithdrawalService.execute_withdrawal(
            user=self.sender,
            payment_method_id=str(self.payment_method.id),
            destination_account="ABA-001234567",
            amount=Decimal("50.0000"),
            pin="123456"
        )
        notif = Notification.objects.filter(
            user=self.sender,
            notification_type=NotificationType.TRANSACTION,
            title="Withdrawal Completed"
        ).first()

        assert notif is not None
        assert "50.00 USD" in notif.message
        assert "ABA-001234567" in notif.message
        assert txn.transaction_code in notif.message

    def test_transfer_generates_notifications_for_both_parties(self):
        txn = TransferService.execute_transfer(
            sender_user=self.sender,
            receiver_wallet_number=self.receiver_wallet.wallet_number,
            amount=Decimal("60.0000"),
            pin="123456",
            description="Dinner split"
        )

        sender_notif = Notification.objects.filter(
            user=self.sender,
            title="Transfer Sent Successfully"
        ).first()
        assert sender_notif is not None
        assert "60.00 USD" in sender_notif.message
        assert "Receiver Meas" in sender_notif.message

        receiver_notif = Notification.objects.filter(
            user=self.receiver,
            title="Money Received"
        ).first()
        assert receiver_notif is not None
        assert "60.00 USD" in receiver_notif.message
        assert "Sender Chan" in receiver_notif.message

    def test_notification_api_list_and_read_endpoints(self):
        self.client.force_authenticate(user=self.sender)

        # Trigger 2 actions to create 2 notifications
        TopUpService.execute_topup(
            user=self.sender,
            payment_method_id=str(self.payment_method.id),
            amount=Decimal("20.0000")
        )
        WithdrawalService.execute_withdrawal(
            user=self.sender,
            payment_method_id=str(self.payment_method.id),
            destination_account="ABA-111",
            amount=Decimal("10.0000"),
            pin="123456"
        )

        # 1. Unread count endpoint
        res = self.client.get("/api/v1/notifications/unread-count/")
        assert res.status_code == 200
        assert res.data["data"]["unread_count"] == 2

        # 2. List notifications endpoint
        res = self.client.get("/api/v1/notifications/")
        assert res.status_code == 200
        data = res.data["data"]
        assert len(data["results"]) == 2
        assert data["unread_count"] == 2

        first_notif_id = data["results"][0]["id"]

        # 3. Mark single notification as read
        res = self.client.patch(f"/api/v1/notifications/{first_notif_id}/read/")
        assert res.status_code == 200
        assert res.data["data"]["is_read"] is True

        res = self.client.get("/api/v1/notifications/unread-count/")
        assert res.data["data"]["unread_count"] == 1

        # 4. Mark all read
        res = self.client.patch("/api/v1/notifications/read-all/")
        assert res.status_code == 200

        res = self.client.get("/api/v1/notifications/unread-count/")
        assert res.data["data"]["unread_count"] == 0
