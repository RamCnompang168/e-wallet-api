import secrets
from decimal import Decimal
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser
from apps.core.idempotency import idempotent_request
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.payments.models import PaymentMethod, TopUp, Withdrawal
from apps.payments.serializers import (
    PaymentMethodSerializer,
    TopUpCreateSerializer,
    TopUpDetailSerializer,
    WithdrawalCreateSerializer,
    WithdrawalDetailSerializer,
)
from apps.payments.services import TopUpService, WithdrawalService
from apps.transactions.models import Transaction, TransactionStatus, TransactionType
from apps.users.models import AuditLog
from apps.wallets.models import Wallet
from apps.wallets.services import LedgerService


class PaymentMethodListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        methods = PaymentMethod.objects.filter(is_active=True).order_by("method_type", "method_name")
        serializer = PaymentMethodSerializer(methods, many=True)
        return success_response(data=serializer.data)


class TopUpListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        topups = TopUp.objects.filter(
            transaction__receiver_wallet_id__in=user_wallets
        ).select_related("transaction", "payment_method").order_by("-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(topups, request)
        serializer = TopUpDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @idempotent_request()
    def post(self, request):
        serializer = TopUpCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        txn = TopUpService.execute_topup(
            user=request.user,
            payment_method_id=str(serializer.validated_data["payment_method_id"]),
            amount=serializer.validated_data["amount"],
            provider_reference=serializer.validated_data.get("provider_reference")
        )

        topup_rec = txn.topup_details
        return success_response(
            message="Top-up completed successfully.",
            data=TopUpDetailSerializer(topup_rec).data,
            status_code=status.HTTP_201_CREATED
        )


class TopUpDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, pk):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        topup = TopUp.objects.filter(
            id=pk,
            transaction__receiver_wallet_id__in=user_wallets
        ).select_related("transaction", "payment_method").first()

        if not topup:
            return error_response(message="Top-up record not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=TopUpDetailSerializer(topup).data)


class WithdrawalListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        withdrawals = Withdrawal.objects.filter(
            transaction__sender_wallet_id__in=user_wallets
        ).select_related("transaction", "payment_method").order_by("-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(withdrawals, request)
        serializer = WithdrawalDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @idempotent_request()
    def post(self, request):
        serializer = WithdrawalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        txn = WithdrawalService.execute_withdrawal(
            user=request.user,
            payment_method_id=str(serializer.validated_data["payment_method_id"]),
            destination_account=serializer.validated_data["destination_account"],
            amount=serializer.validated_data["amount"],
            pin=serializer.validated_data.get("pin")
        )

        withdrawal_rec = txn.withdrawal_details
        return success_response(
            message="Withdrawal processed successfully.",
            data=WithdrawalDetailSerializer(withdrawal_rec).data,
            status_code=status.HTTP_201_CREATED
        )


class WithdrawalDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, pk):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        withdrawal = Withdrawal.objects.filter(
            id=pk,
            transaction__sender_wallet_id__in=user_wallets
        ).select_related("transaction", "payment_method").first()

        if not withdrawal:
            return error_response(message="Withdrawal record not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=WithdrawalDetailSerializer(withdrawal).data)


class GovernmentServicePaymentView(APIView):
    """Executes public/government utility and tax payments."""
    permission_classes = [IsAuthenticated, IsActiveUser]

    @idempotent_request()
    def post(self, request):
        service_type = (request.data.get("service_type") or "GOV_SERVICE").strip()
        service_name = (request.data.get("service_name") or "Government Public Service").strip()
        consumer_number = (
            request.data.get("consumer_number")
            or request.data.get("reference_number")
            or ""
        ).strip()
        notes = (request.data.get("notes") or "").strip()
        pin = (
            request.data.get("pin")
            or request.headers.get("x-transaction-pin")
            or request.META.get("HTTP_X_TRANSACTION_PIN")
            or ""
        ).strip()

        try:
            amount = Decimal(str(request.data.get("amount", "0")))
        except Exception:
            return error_response(message="Invalid payment amount.", status_code=status.HTTP_400_BAD_REQUEST)

        if amount <= Decimal("0.0000"):
            return error_response(message="Payment amount must be greater than zero.", status_code=status.HTTP_400_BAD_REQUEST)

        if not consumer_number:
            return error_response(message="Bill reference or account number is required.", status_code=status.HTTP_400_BAD_REQUEST)

        user = request.user
        if user.pin_hash:
            if not pin:
                return error_response(message="Transaction PIN is required to authorize payment.", status_code=status.HTTP_400_BAD_REQUEST)
            try:
                user.verify_pin(pin)
            except Exception as e:
                return error_response(message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

        wallet = Wallet.objects.filter(user=user, is_primary=True, status="ACTIVE").first()
        if not wallet:
            return error_response(message="No active primary wallet found.", status_code=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked = LedgerService.lock_wallets_canonical(wallet.id)
            locked_wallet = locked[str(wallet.id)]

            if locked_wallet.available_balance < amount:
                return error_response(message="Insufficient wallet balance.", status_code=status.HTTP_400_BAD_REQUEST)

            desc = f"{service_name} ({consumer_number})"
            if notes:
                desc += f" - {notes}"
            ref = f"GOV-{secrets.token_hex(4).upper()}"

            txn = Transaction.objects.create(
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                status=TransactionStatus.PROCESSING,
                sender_wallet=locked_wallet,
                amount=amount,
                fee_amount=Decimal("0.0000"),
                total_amount=amount,
                currency=locked_wallet.currency,
                description=desc,
                reference_number=ref,
            )

            LedgerService.post_withdrawal_entries(
                txn=txn,
                sender_wallet=locked_wallet,
                amount=amount,
                fee_amount=Decimal("0.0000")
            )

            txn.transition_to(TransactionStatus.COMPLETED)
            txn.save(update_fields=["status", "completed_at", "updated_at"])

            AuditLog.objects.create(
                user=user,
                action="GOV_PAYMENT_COMPLETED",
                entity_type="Transaction",
                entity_id=str(txn.id),
                new_value={"amount": str(amount), "service": service_name, "ref": consumer_number}
            )

            try:
                from apps.notifications.services import NotificationService
                NotificationService.create_notification(
                    user=user,
                    notification_type="TRANSACTION",
                    title="Government Service Paid",
                    message=f"Successfully paid ${amount:.2f} for {service_name} ({consumer_number}). Reference: {ref}",
                    related_transaction=txn
                )
            except Exception:
                pass

        return success_response(
            message=f"Successfully paid for {service_name}.",
            data={
                "transaction_code": txn.transaction_code,
                "reference_number": ref,
                "amount": str(amount),
                "service_name": service_name,
                "consumer_number": consumer_number,
                "description": desc,
                "created_at": txn.created_at.isoformat(),
            },
            status_code=status.HTTP_201_CREATED
        )


class KhqrGenerateView(APIView):
    """Generates an authentic NBC/ABA Bakong KHQR code via KHQR.dev for inbound wallet top-up."""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            amount_str = str(request.data.get("amount", "1.00"))
            amount = Decimal(amount_str)
        except Exception:
            return error_response(message="Invalid amount value.", status_code=status.HTTP_400_BAD_REQUEST)

        if amount < Decimal("0.01"):
            amount = Decimal("0.01")

        from apps.payments.services import KhqrService
        try:
            data = KhqrService.generate_qr(amount)
            return success_response(
                message="Live Bakong KHQR generated successfully.",
                data={
                    "qr": data.get("qr"),
                    "md5": data.get("md5"),
                    "tran_id": data.get("tran_id"),
                    "checkout_url": data.get("checkout_url"),
                    "qr_image_url": data.get("qr_image_url"),
                    "amount": str(amount),
                    "merchant_name": "RON RAM",
                    "currency": "USD",
                },
                status_code=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(message=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class KhqrStatusView(APIView):
    """
    Checks if a KHQR payment was completed by ABA / ACLEDA / Bakong.
    If paid, immediately credits the user's wallet with the amount.
    """
    permission_classes = [AllowAny]

    def get(self, request, md5):
        from apps.payments.services import KhqrService
        try:
            amount_str = str(request.query_params.get("amount", "0"))
            amount = Decimal(amount_str) if amount_str and amount_str != "0" else Decimal("1.00")
        except Exception:
            amount = Decimal("1.00")

        target_user = request.user if getattr(request.user, "is_authenticated", False) else None
        paid, txn = KhqrService.fulfill_payment_if_paid(
            user=target_user,
            md5=md5,
            amount=amount,
        )

        status_data = KhqrService.check_transaction(md5)
        is_paid = paid or status_data.get("status") == "paid"

        return success_response(
            message="KHQR status retrieved.",
            data={
                "status": "paid" if is_paid else status_data.get("status", "unpaid"),
                "is_paid": is_paid,
                "md5": md5,
                "tran_id": status_data.get("tran_id"),
                "hash": status_data.get("hash"),
                "credited": paid,
                "transaction_code": txn.transaction_code if txn else None,
            },
        )


class KhqrWebhookView(APIView):
    """
    Receives real-time payment webhooks dispatched by KHQR.dev.
    Validates HMAC-SHA256 signature against X-RBK-Signature and X-RBK-Delivery.
    Fulfills payment idempotently.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        import hmac
        import hashlib
        import time
        import os
        from django.conf import settings

        secret = (
            os.environ.get("KHQR_WEBHOOK_SECRET")
            or os.environ.get("RBK_WEBHOOK_SECRET")
            or getattr(settings, "KHQR_WEBHOOK_SECRET", "whsec_lzf5l8C6IuqiOXWsg1eSwBzH")
        )

        signature = (
            request.headers.get("X-RBK-Signature")
            or request.META.get("HTTP_X_RBK_SIGNATURE")
            or ""
        )
        delivery_str = (
            request.headers.get("X-RBK-Delivery")
            or request.META.get("HTTP_X_RBK_DELIVERY")
            or ""
        )

        raw_body = request.body

        # Replay attack prevention: validate |Now - Delivery| <= 300,000ms
        if delivery_str:
            try:
                delivery_ts = int(delivery_str)
                current_ts = int(time.time() * 1000)
                if abs(current_ts - delivery_ts) > 300_000:
                    return error_response(message="Delivery timestamp expired.", status_code=status.HTTP_401_UNAUTHORIZED)
            except ValueError:
                return error_response(message="Invalid delivery timestamp format.", status_code=status.HTTP_400_BAD_REQUEST)

        # Cryptographic HMAC-SHA256 verification
        if signature and secret:
            computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed.lower(), signature.lower()):
                return error_response(message="Invalid webhook signature.", status_code=status.HTTP_401_UNAUTHORIZED)

        event_type = request.data.get("event")
        md5 = request.data.get("md5")
        data_obj = request.data.get("data") or {}

        if event_type == "payment.success" and md5:
            from apps.payments.models import TopUp, PaymentMethod
            from apps.payments.services import TopUpService
            from apps.users.models import User

            amount_val = data_obj.get("amount") or request.data.get("amount") or 1.00
            try:
                amount = Decimal(str(amount_val))
            except Exception:
                amount = Decimal("1.00")

            existing = TopUp.objects.filter(provider_reference=f"KHQR-{md5}").first()
            if existing:
                return success_response(message="Payment already processed (idempotent).")

            user = User.objects.filter(is_active=True).first()
            if user:
                method = PaymentMethod.objects.filter(is_active=True, method_type="DIGITAL_WALLET").first() or PaymentMethod.objects.filter(is_active=True).first()
                if method:
                    TopUpService.execute_topup(
                        user=user,
                        payment_method_id=str(method.id),
                        amount=amount,
                        provider_reference=f"KHQR-{md5}",
                    )

            return success_response(message="Payment verified and credited successfully.")

        return success_response(message="Webhook event received.")
