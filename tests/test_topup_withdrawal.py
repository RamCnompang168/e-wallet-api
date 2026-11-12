from decimal import Decimal
import pytest

from apps.core.exceptions import InsufficientBalanceException, KYCRequiredException
from apps.payments.models import PaymentMethod, PaymentMethodType, TopUpStatus, WithdrawalStatus
from apps.payments.services import TopUpService, WithdrawalService
from apps.users.models import User
from apps.wallets.models import SystemAccount, SystemAccountCode, Wallet


@pytest.mark.django_db
class TestTopUpAndWithdrawal:
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

        self.user = User.objects.create_user(
            email="paymentuser@example.com",
            phone_number="+19990001111",
            password="Password123!",
            full_name="Payment User",
            kyc_tier=1  # Verified
        )
        self.user.set_pin("123456")
        self.user.save()

        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.available_balance = Decimal("200.0000")
        self.wallet.current_balance = Decimal("200.0000")
        self.wallet.save()

    def test_topup_success(self):
        txn = TopUpService.execute_topup(
            user=self.user,
            payment_method_id=str(self.payment_method.id),
            amount=Decimal("150.0000")
        )

        assert txn.topup_details.status == TopUpStatus.COMPLETED
        self.wallet.refresh_from_db()
        # 200 + 150 = 350
        assert self.wallet.available_balance == Decimal("350.0000")

    def test_withdrawal_success_with_kyc(self):
        txn = WithdrawalService.execute_withdrawal(
            user=self.user,
            payment_method_id=str(self.payment_method.id),
            destination_account="US1234567890",
            amount=Decimal("100.0000"),
            pin="123456"
        )

        assert txn.withdrawal_details.status == WithdrawalStatus.COMPLETED
        self.wallet.refresh_from_db()
        # 200 - 100 = 100
        assert self.wallet.available_balance == Decimal("100.0000")

    def test_withdrawal_blocked_without_kyc(self):
        unverified_user = User.objects.create_user(
            email="unverified@example.com",
            phone_number="+19990002222",
            password="Password123!",
            full_name="Unverified User",
            kyc_tier=0  # Tier 0 Unverified
        )
        unverified_user.set_pin("123456")
        unverified_user.save()

        w = Wallet.objects.get(user=unverified_user)
        w.available_balance = Decimal("500.0000")
        w.save()

        with pytest.raises(KYCRequiredException):
            WithdrawalService.execute_withdrawal(
                user=unverified_user,
                payment_method_id=str(self.payment_method.id),
                destination_account="US99999",
                amount=Decimal("50.0000"),
                pin="123456"
            )

    def test_withdrawal_insufficient_balance(self):
        with pytest.raises(InsufficientBalanceException):
            WithdrawalService.execute_withdrawal(
                user=self.user,
                payment_method_id=str(self.payment_method.id),
                destination_account="US1234567890",
                amount=Decimal("500.0000"),
                pin="123456"
            )
