import os
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.merchants.models import Merchant, MerchantStatus
from apps.payments.models import PaymentMethod, PaymentMethodType
from apps.transactions.models import FeeRule, TransactionLimit, TransactionType
from apps.users.models import Gender, User, UserRole, UserStatus
from apps.wallets.models import SystemAccount, SystemAccountCode, Wallet
from apps.wallets.services import LedgerService


class Command(BaseCommand):
    help = "Seeds initial roles, system accounts, payment rails, limits, fee rules, and demo accounts."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting database seeding..."))

        with transaction.atomic():
            # 1. System Balancing Accounts (Double-Entry Invariant)
            self.stdout.write("1. Seeding system accounts...")
            SystemAccount.get_or_create_system_account(SystemAccountCode.FEE_REVENUE, currency="USD")
            SystemAccount.get_or_create_system_account(SystemAccountCode.SETTLEMENT_ESCROW, currency="USD")
            SystemAccount.get_or_create_system_account(SystemAccountCode.EXTERNAL_CLEARING, currency="USD")

            # 2. Payment Methods
            self.stdout.write("2. Seeding payment rails...")
            rails = [
                ("Visa / MasterCard Gateway", PaymentMethodType.CARD, "StripeSim"),
                ("Instant Bank Direct Debit", PaymentMethodType.BANK_TRANSFER, "PlaidSim"),
                ("Fast National QR Settlement", PaymentMethodType.DIGITAL_WALLET, "BakongSim"),
                ("Authorized Cash Agent Deposit", PaymentMethodType.CASH_AGENT, "NovaAgentNetwork"),
            ]
            for name, m_type, provider in rails:
                PaymentMethod.objects.get_or_create(
                    method_name=name,
                    defaults={"method_type": m_type, "provider_name": provider, "is_active": True}
                )

            # 3. Fee Rules
            self.stdout.write("3. Seeding dynamic fee rules...")
            fee_configs = [
                (TransactionType.TRANSFER, Decimal("0.2500"), Decimal("0.0050"), Decimal("0.2500"), Decimal("5.0000")),
                (TransactionType.TOPUP, Decimal("0.0000"), Decimal("0.0000"), Decimal("0.0000"), None),
                (TransactionType.WITHDRAWAL, Decimal("1.5000"), Decimal("0.0000"), Decimal("1.5000"), Decimal("10.0000")),
                (TransactionType.MERCHANT_PAYMENT, Decimal("0.0000"), Decimal("0.0150"), Decimal("0.0000"), None),
            ]
            for txn_type, fixed, pct, min_f, max_f in fee_configs:
                FeeRule.objects.update_or_create(
                    transaction_type=txn_type,
                    defaults={
                        "fixed_fee": fixed,
                        "percentage_fee": pct,
                        "min_fee": min_f,
                        "max_fee": max_f,
                        "is_active": True,
                    }
                )

            # 4. Transaction Limits
            self.stdout.write("4. Seeding transaction velocity limits...")
            limit_configs = [
                # Role, KYC Tier, TxnType, Min, MaxPerTxn, MaxPerDay, MaxPerMonth
                (UserRole.CUSTOMER, 0, TransactionType.TRANSFER, Decimal("1.00"), Decimal("500.00"), Decimal("1000.00"), Decimal("5000.00")),
                (UserRole.CUSTOMER, 1, TransactionType.TRANSFER, Decimal("1.00"), Decimal("5000.00"), Decimal("20000.00"), Decimal("50000.00")),
                (UserRole.CUSTOMER, 2, TransactionType.TRANSFER, Decimal("1.00"), Decimal("25000.00"), Decimal("100000.00"), Decimal("300000.00")),
                (UserRole.MERCHANT, 1, TransactionType.TRANSFER, Decimal("1.00"), Decimal("50000.00"), Decimal("200000.00"), Decimal("1000000.00")),
                (UserRole.CUSTOMER, 1, TransactionType.WITHDRAWAL, Decimal("5.00"), Decimal("2000.00"), Decimal("5000.00"), Decimal("20000.00")),
            ]
            for role, tier, t_type, min_a, max_txn, max_d, max_m in limit_configs:
                TransactionLimit.objects.update_or_create(
                    role=role,
                    kyc_tier=tier,
                    transaction_type=t_type,
                    currency="USD",
                    defaults={
                        "minimum_amount": min_a,
                        "maximum_per_transaction": max_txn,
                        "maximum_per_day": max_d,
                        "maximum_per_month": max_m,
                        "is_active": True,
                    }
                )

            # 5. Core Users and Demo Wallets
            self.stdout.write("5. Seeding users, wallets, and demo balances...")

            # Super Admin
            admin_user, _ = User.objects.get_or_create(
                email="admin@novapay.bank",
                defaults={
                    "phone_number": "+85512000001",
                    "full_name": "Dara Sok",
                    "role": UserRole.SUPER_ADMIN,
                    "status": UserStatus.ACTIVE,
                    "is_staff": True,
                    "is_superuser": True,
                    "is_email_verified": True,
                    "is_phone_verified": True,
                    "kyc_tier": 2,
                }
            )
            admin_user.full_name = "Dara Sok"
            admin_user.set_password("AdminSecurePass123!")
            admin_user.set_pin("123456")
            admin_user.save()

            # Compliance / Staff
            staff_user, _ = User.objects.get_or_create(
                email="compliance@novapay.bank",
                defaults={
                    "phone_number": "+85512000002",
                    "full_name": "Kosal Vichea",
                    "role": UserRole.STAFF,
                    "status": UserStatus.ACTIVE,
                    "is_staff": True,
                    "is_email_verified": True,
                    "is_phone_verified": True,
                    "kyc_tier": 2,
                }
            )
            staff_user.full_name = "Kosal Vichea"
            staff_user.set_password("StaffSecurePass123!")
            staff_user.set_pin("123456")
            staff_user.save()

            # Merchant: Brown Coffee Roasters
            merchant_user, _ = User.objects.get_or_create(
                email="coffee@shop.com",
                defaults={
                    "phone_number": "+85512000003",
                    "full_name": "Brown Coffee Roasters",
                    "role": UserRole.MERCHANT,
                    "status": UserStatus.ACTIVE,
                    "is_email_verified": True,
                    "is_phone_verified": True,
                    "kyc_tier": 2,
                }
            )
            merchant_user.full_name = "Brown Coffee Roasters"
            merchant_user.set_password("MerchantPass123!")
            merchant_user.set_pin("123456")
            merchant_user.save()

            Merchant.objects.get_or_create(
                owner=merchant_user,
                defaults={
                    "business_name": "Brown Coffee Roasters",
                    "phone_number": "+85512000003",
                    "email": "coffee@shop.com",
                    "status": MerchantStatus.ACTIVE,
                    "fee_rate": Decimal("0.0150"),
                }
            )

            # Customer Sokha ($1,000.00 funding)
            alice, _ = User.objects.get_or_create(
                email="alice@example.com",
                defaults={
                    "phone_number": "+85512345678",
                    "full_name": "Sokha Chan",
                    "role": UserRole.CUSTOMER,
                    "status": UserStatus.ACTIVE,
                    "is_email_verified": True,
                    "is_phone_verified": True,
                    "kyc_tier": 1,
                    "gender": Gender.FEMALE,
                }
            )
            alice.full_name = "Sokha Chan"
            alice.set_password("AlicePass123!")
            alice.set_pin("123456")
            alice.save()

            alice_wallet, _ = Wallet.objects.get_or_create(
                user=alice,
                is_primary=True,
                defaults={"currency": "USD", "current_balance": Decimal("1000.0000"), "available_balance": Decimal("1000.0000")}
            )
            if alice_wallet.available_balance == Decimal("0.0000"):
                alice_wallet.available_balance = Decimal("1000.0000")
                alice_wallet.current_balance = Decimal("1000.0000")
                alice_wallet.save()

            # Customer Thida ($250.00 funding)
            bob, _ = User.objects.get_or_create(
                email="bob@example.com",
                defaults={
                    "phone_number": "+85598765432",
                    "full_name": "Thida Meas",
                    "role": UserRole.CUSTOMER,
                    "status": UserStatus.ACTIVE,
                    "is_email_verified": True,
                    "is_phone_verified": True,
                    "kyc_tier": 1,
                    "gender": Gender.FEMALE,
                }
            )
            bob.full_name = "Thida Meas"
            bob.set_password("BobPass123!")
            bob.set_pin("123456")
            bob.save()

            bob_wallet, _ = Wallet.objects.get_or_create(
                user=bob,
                is_primary=True,
                defaults={"currency": "USD", "current_balance": Decimal("250.0000"), "available_balance": Decimal("250.0000")}
            )
            if bob_wallet.available_balance == Decimal("0.0000"):
                bob_wallet.available_balance = Decimal("250.0000")
                bob_wallet.current_balance = Decimal("250.0000")
                bob_wallet.save()

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
        self.stdout.write(self.style.SUCCESS(f"  Super Admin : admin@novapay.bank / AdminSecurePass123! (PIN: 123456)"))
        self.stdout.write(self.style.SUCCESS(f"  Compliance  : compliance@novapay.bank / StaffSecurePass123! (PIN: 123456)"))
        self.stdout.write(self.style.SUCCESS(f"  Merchant    : coffee@shop.com / MerchantPass123! (PIN: 123456)"))
        self.stdout.write(self.style.SUCCESS(f"  Alice       : alice@example.com / AlicePass123! (PIN: 123456, Bal: $1,000)"))
        self.stdout.write(self.style.SUCCESS(f"  Bob         : bob@example.com / BobPass123! (PIN: 123456, Bal: $250)"))
