import logging
from decimal import Decimal
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.transactions.models import Transaction, TransactionStatus, TransactionType
from apps.wallets.models import LedgerEntry, LedgerEntryType, Wallet, WalletStatus
from apps.wallets.serializers import LedgerEntrySerializer, WalletBalanceSerializer, WalletSerializer

logger = logging.getLogger("banking.wallets")

EXCHANGE_RATE_USD_TO_KHR = Decimal("4050.0000")


class WalletDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        wallet = Wallet.objects.filter(user=request.user, is_primary=True).first()
        if not wallet:
            # Fallback to any wallet or create one
            wallet = Wallet.objects.filter(user=request.user).first()

        if not wallet:
            wallet = Wallet.objects.create(
                user=request.user,
                currency="USD",
                is_primary=True,
                status=WalletStatus.ACTIVE,
                current_balance=Decimal("0.0000"),
                available_balance=Decimal("0.0000"),
                hold_balance=Decimal("0.0000"),
            )

        khr_wallet, _ = Wallet.objects.get_or_create(
            user=request.user,
            currency="KHR",
            defaults={
                "is_primary": False,
                "status": WalletStatus.ACTIVE,
                "current_balance": Decimal("0.0000"),
                "available_balance": Decimal("0.0000"),
                "hold_balance": Decimal("0.0000"),
            }
        )

        all_wallets = list(Wallet.objects.filter(user=request.user).order_by("-is_primary", "currency"))
        serializer = WalletSerializer(wallet)
        data = dict(serializer.data)
        data["khr_wallet"] = WalletSerializer(khr_wallet).data
        data["all_wallets"] = WalletSerializer(all_wallets, many=True).data
        return success_response(data=data)


class UserWalletsListView(APIView):
    """List all wallets (USD and KHR) belonging to current user."""
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        # Ensure at least primary wallet exists
        primary = Wallet.objects.filter(user=request.user, is_primary=True).first()
        if not primary:
            Wallet.objects.create(
                user=request.user,
                currency="USD",
                is_primary=True,
                status=WalletStatus.ACTIVE,
                current_balance=Decimal("0.0000"),
                available_balance=Decimal("0.0000"),
                hold_balance=Decimal("0.0000"),
            )

        Wallet.objects.get_or_create(
            user=request.user,
            currency="KHR",
            defaults={
                "is_primary": False,
                "status": WalletStatus.ACTIVE,
                "current_balance": Decimal("0.0000"),
                "available_balance": Decimal("0.0000"),
                "hold_balance": Decimal("0.0000"),
            }
        )

        wallets = Wallet.objects.filter(user=request.user).order_by("-is_primary", "currency")
        serializer = WalletSerializer(wallets, many=True)
        return success_response(data=serializer.data)


class CreateKhrWalletView(APIView):
    """Create or retrieve the Khmer Riel (KHR) card/wallet for current user."""
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request):
        khr_wallet, created = Wallet.objects.get_or_create(
            user=request.user,
            currency="KHR",
            defaults={
                "is_primary": False,
                "status": WalletStatus.ACTIVE,
                "current_balance": Decimal("0.0000"),
                "available_balance": Decimal("0.0000"),
                "hold_balance": Decimal("0.0000"),
            }
        )
        serializer = WalletSerializer(khr_wallet)
        msg = "KHR wallet created successfully." if created else "KHR wallet retrieved."
        return success_response(data=serializer.data, message=msg)


class WalletExchangeView(APIView):
    """
    Exchange currency between USD and KHR wallets for current user.
    Standard rate: 1 USD = 4,050 KHR.
    """
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request):
        from_curr = (request.data.get("from_currency") or "USD").upper().strip()
        to_curr = (request.data.get("to_currency") or "KHR").upper().strip()
        raw_amount = request.data.get("amount")

        if from_curr not in ["USD", "KHR"] or to_curr not in ["USD", "KHR"]:
            return error_response(message="Currencies must be either USD or KHR.", status_code=400)

        if from_curr == to_curr:
            return error_response(message="Source and target currencies must be different.", status_code=400)

        try:
            amount = Decimal(str(raw_amount))
            if amount <= Decimal("0.0000"):
                raise ValueError()
        except Exception:
            return error_response(message="Please provide a valid positive amount to exchange.", status_code=400)

        with db_transaction.atomic():
            # Get or create wallets
            usd_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                user=request.user,
                currency="USD",
                defaults={"is_primary": True, "status": WalletStatus.ACTIVE}
            )
            khr_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                user=request.user,
                currency="KHR",
                defaults={"is_primary": False, "status": WalletStatus.ACTIVE}
            )

            if from_curr == "USD":
                if usd_wallet.available_balance < amount:
                    return error_response(
                        message=f"Insufficient USD balance. Available: ${usd_wallet.available_balance:.2f}",
                        status_code=400
                    )
                khr_received = (amount * EXCHANGE_RATE_USD_TO_KHR).quantize(Decimal("1.0000"))
                
                # Debit USD
                usd_before = usd_wallet.current_balance
                usd_wallet.current_balance -= amount
                usd_wallet.available_balance -= amount
                usd_wallet.save(update_fields=["current_balance", "available_balance", "updated_at"])

                # Credit KHR
                khr_before = khr_wallet.current_balance
                khr_wallet.current_balance += khr_received
                khr_wallet.available_balance += khr_received
                khr_wallet.save(update_fields=["current_balance", "available_balance", "updated_at"])

                # Create Transaction record
                txn = Transaction.objects.create(
                    transaction_type=TransactionType.TRANSFER,
                    status=TransactionStatus.COMPLETED,
                    sender_wallet=usd_wallet,
                    receiver_wallet=khr_wallet,
                    amount=amount,
                    fee_amount=Decimal("0.0000"),
                    total_amount=amount,
                    currency="USD",
                    description=f"Exchanged ${amount:.2f} USD → {int(khr_received):,} KHR (Rate: 1 USD = 4,050 KHR)",
                    completed_at=timezone.now(),
                    metadata={
                        "exchange": True,
                        "from_currency": "USD",
                        "to_currency": "KHR",
                        "rate": 4050,
                        "khr_received": str(khr_received),
                    }
                )

                # Ledger records
                LedgerEntry.objects.create(
                    wallet=usd_wallet,
                    transaction=txn,
                    entry_type=LedgerEntryType.DEBIT,
                    amount=amount,
                    balance_before=usd_before,
                    balance_after=usd_wallet.current_balance,
                    description=f"Exchange debit: ${amount:.2f} USD to KHR"
                )
                LedgerEntry.objects.create(
                    wallet=khr_wallet,
                    transaction=txn,
                    entry_type=LedgerEntryType.CREDIT,
                    amount=khr_received,
                    balance_before=khr_before,
                    balance_after=khr_wallet.current_balance,
                    description=f"Exchange credit: {int(khr_received):,} KHR from USD"
                )

                return success_response(
                    data={
                        "from_currency": "USD",
                        "to_currency": "KHR",
                        "from_amount": float(amount),
                        "to_amount": float(khr_received),
                        "rate": 4050,
                        "usd_wallet": WalletSerializer(usd_wallet).data,
                        "khr_wallet": WalletSerializer(khr_wallet).data,
                    },
                    message=f"Successfully converted ${amount:.2f} USD to {int(khr_received):,} KHR."
                )

            else: # from KHR to USD
                if khr_wallet.available_balance < amount:
                    return error_response(
                        message=f"Insufficient KHR balance. Available: {int(khr_wallet.available_balance):,} KHR",
                        status_code=400
                    )
                usd_received = (amount / EXCHANGE_RATE_USD_TO_KHR).quantize(Decimal("0.0100"))
                if usd_received <= Decimal("0.0000"):
                    return error_response(
                        message="Exchange amount is too small. Minimum is 41 KHR ($0.01 USD).",
                        status_code=400
                    )

                # Debit KHR
                khr_before = khr_wallet.current_balance
                khr_wallet.current_balance -= amount
                khr_wallet.available_balance -= amount
                khr_wallet.save(update_fields=["current_balance", "available_balance", "updated_at"])

                # Credit USD
                usd_before = usd_wallet.current_balance
                usd_wallet.current_balance += usd_received
                usd_wallet.available_balance += usd_received
                usd_wallet.save(update_fields=["current_balance", "available_balance", "updated_at"])

                # Create Transaction record
                txn = Transaction.objects.create(
                    transaction_type=TransactionType.TRANSFER,
                    status=TransactionStatus.COMPLETED,
                    sender_wallet=khr_wallet,
                    receiver_wallet=usd_wallet,
                    amount=amount,
                    fee_amount=Decimal("0.0000"),
                    total_amount=amount,
                    currency="KHR",
                    description=f"Exchanged {int(amount):,} KHR → ${usd_received:.2f} USD (Rate: 1 USD = 4,050 KHR)",
                    completed_at=timezone.now(),
                    metadata={
                        "exchange": True,
                        "from_currency": "KHR",
                        "to_currency": "USD",
                        "rate": 4050,
                        "usd_received": str(usd_received),
                    }
                )

                # Ledger records
                LedgerEntry.objects.create(
                    wallet=khr_wallet,
                    transaction=txn,
                    entry_type=LedgerEntryType.DEBIT,
                    amount=amount,
                    balance_before=khr_before,
                    balance_after=khr_wallet.current_balance,
                    description=f"Exchange debit: {int(amount):,} KHR to USD"
                )
                LedgerEntry.objects.create(
                    wallet=usd_wallet,
                    transaction=txn,
                    entry_type=LedgerEntryType.CREDIT,
                    amount=usd_received,
                    balance_before=usd_before,
                    balance_after=usd_wallet.current_balance,
                    description=f"Exchange credit: ${usd_received:.2f} USD from KHR"
                )

                return success_response(
                    data={
                        "from_currency": "KHR",
                        "to_currency": "USD",
                        "from_amount": float(amount),
                        "to_amount": float(usd_received),
                        "rate": 4050,
                        "usd_wallet": WalletSerializer(usd_wallet).data,
                        "khr_wallet": WalletSerializer(khr_wallet).data,
                    },
                    message=f"Successfully converted {int(amount):,} KHR to ${usd_received:.2f} USD."
                )


class WalletBalanceView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        wallet = Wallet.objects.filter(user=request.user, is_primary=True).first()
        if not wallet:
            return error_response(message="Wallet not found.", status_code=404)

        serializer = WalletBalanceSerializer(wallet)
        return success_response(data=serializer.data)


class WalletLedgerView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        wallet = Wallet.objects.filter(user=request.user, is_primary=True).first()
        if not wallet:
            return error_response(message="Wallet not found.", status_code=404)

        entries = LedgerEntry.objects.filter(wallet=wallet).select_related("transaction").order_by("-created_at")

        # Optional date filtering
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            entries = entries.filter(created_at__date__gte=start_date)
        if end_date:
            entries = entries.filter(created_at__date__lte=end_date)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(entries, request)
        serializer = LedgerEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminWalletListView(APIView):
    """Staff/Admin view to list and filter all wallets."""
    from apps.authentication.permissions import IsStaffMember
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        wallets = Wallet.objects.all().select_related("user").order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            wallets = wallets.filter(status=status_filter.upper())

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(wallets, request)
        serializer = WalletSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminSystemAccountListView(APIView):
    """Staff/Admin view to inspect internal double-entry balancing accounts and fee revenues."""
    from apps.authentication.permissions import IsStaffMember
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        from apps.wallets.models import SystemAccount
        accounts = SystemAccount.objects.all().order_by("account_code")
        data = [
            {
                "id": str(acc.id),
                "account_code": acc.account_code,
                "account_name": acc.account_name,
                "currency": acc.currency,
                "balance": str(acc.balance),
                "description": acc.description,
            }
            for acc in accounts
        ]
        return success_response(data=data)

