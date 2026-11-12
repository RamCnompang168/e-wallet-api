from decimal import Decimal
import pytest

from apps.core.exceptions import BankingException
from apps.merchants.models import DisputeStatus, DisputeType, Merchant, MerchantStatus, RefundStatus
from apps.merchants.services import DisputeService, MerchantPaymentService, RefundService
from apps.transactions.models import TransactionStatus, TransactionType
from apps.users.models import User, UserRole
from apps.wallets.models import SystemAccount, SystemAccountCode, Wallet


@pytest.mark.django_db
class TestMerchantsRefundsDisputes:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        SystemAccount.get_or_create_system_account(SystemAccountCode.FEE_REVENUE, currency="USD")

        # Admin
        self.admin = User.objects.create_superuser(
            email="admin.mch@novapay.bank",
            phone_number="+10001112222",
            password="AdminPass123!"
        )

        # Merchant
        self.merchant_owner = User.objects.create_user(
            email="merchant.owner@example.com",
            phone_number="+10003334444",
            password="Password123!",
            role=UserRole.MERCHANT
        )
        self.merchant = Merchant.objects.create(
            owner=self.merchant_owner,
            business_name="SuperMart",
            merchant_code="MCH-TEST-01",
            fee_rate=Decimal("0.0200")  # 2% MDR
        )
        self.merchant_wallet = Wallet.objects.get(user=self.merchant_owner)

        # Customer
        self.customer = User.objects.create_user(
            email="shopper@example.com",
            phone_number="+10005556666",
            password="Password123!"
        )
        self.customer_wallet = Wallet.objects.get(user=self.customer)
        self.customer_wallet.available_balance = Decimal("500.0000")
        self.customer_wallet.current_balance = Decimal("500.0000")
        self.customer_wallet.save()

    def test_merchant_payment_and_mdr_fee(self):
        txn = MerchantPaymentService.execute_merchant_payment(
            customer_user=self.customer,
            merchant_code="MCH-TEST-01",
            amount=Decimal("100.0000"),
            customer_note="Groceries"
        )

        assert txn.status == TransactionStatus.COMPLETED
        # MDR Fee: 2% of $100 = $2.00
        assert txn.fee_amount == Decimal("2.0000")

        self.customer_wallet.refresh_from_db()
        self.merchant_wallet.refresh_from_db()

        # Customer debited $100 -> 500 - 100 = 400
        assert self.customer_wallet.available_balance == Decimal("400.0000")
        # Merchant credited $100 - $2 = $98
        assert self.merchant_wallet.available_balance == Decimal("98.0000")

    def test_full_and_partial_refund(self):
        txn = MerchantPaymentService.execute_merchant_payment(
            customer_user=self.customer,
            merchant_code="MCH-TEST-01",
            amount=Decimal("100.0000")
        )

        # Merchant initiates partial refund of $30
        refund1 = RefundService.process_refund(
            initiator_user=self.merchant_owner,
            original_transaction_id=str(txn.id),
            amount=Decimal("30.0000"),
            reason="Item returned"
        )
        assert refund1.status == RefundStatus.COMPLETED

        txn.refresh_from_db()
        assert txn.status == TransactionStatus.PARTIALLY_REFUNDED

        # Attempt to over-refund $80 (30 + 80 = 110 > 100) must fail!
        with pytest.raises(BankingException):
            RefundService.process_refund(
                initiator_user=self.merchant_owner,
                original_transaction_id=str(txn.id),
                amount=Decimal("80.0000"),
                reason="Over-refund attempt"
            )

        # Complete refund with remaining $70
        refund2 = RefundService.process_refund(
            initiator_user=self.merchant_owner,
            original_transaction_id=str(txn.id),
            amount=Decimal("70.0000"),
            reason="Remaining refund"
        )
        assert refund2.status == RefundStatus.COMPLETED

        txn.refresh_from_db()
        assert txn.status == TransactionStatus.REFUNDED

    def test_dispute_and_resolution_flow(self):
        txn = MerchantPaymentService.execute_merchant_payment(
            customer_user=self.customer,
            merchant_code="MCH-TEST-01",
            amount=Decimal("50.0000")
        )

        # Customer files dispute
        dispute = DisputeService.file_dispute(
            user=self.customer,
            transaction_id=str(txn.id),
            dispute_type=DisputeType.GOODS_NOT_RECEIVED,
            reason="Item never arrived at delivery address."
        )
        assert dispute.status == DisputeStatus.OPEN

        # Admin resolves dispute in customer's favor (accepts refund)
        resolved = DisputeService.resolve_dispute(
            reviewer_user=self.admin,
            dispute_id=str(dispute.id),
            decision=DisputeStatus.ACCEPTED,
            resolution_notes="Merchant tracking showed delivery failure. Refund granted."
        )

        assert resolved.status == DisputeStatus.ACCEPTED
        txn.refresh_from_db()
        assert txn.status == TransactionStatus.REFUNDED
