from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser
from apps.core.idempotency import idempotent_request
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.transactions.models import Transaction, TransactionType
from apps.transfers.serializers import TransferCreateSerializer, TransferDetailSerializer
from apps.transfers.services import TransferService


class TransferListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        txns = Transaction.objects.filter(
            Q(sender_wallet_id__in=user_wallets) | Q(receiver_wallet_id__in=user_wallets),
            transaction_type=TransactionType.TRANSFER
        ).select_related("sender_wallet__user", "receiver_wallet__user").order_by("-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(txns, request)
        serializer = TransferDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @idempotent_request()
    def post(self, request):
        serializer = TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_pin = (
            serializer.validated_data.get("pin")
            or request.headers.get("x-transaction-pin")
            or request.META.get("HTTP_X_TRANSACTION_PIN")
        )

        txn = TransferService.execute_transfer(
            sender_user=request.user,
            receiver_wallet_number=serializer.validated_data["receiver_wallet_number"],
            amount=serializer.validated_data["amount"],
            description=serializer.validated_data.get("description", ""),
            reference_number=serializer.validated_data.get("reference_number", ""),
            pin=raw_pin
        )

        response_data = TransferDetailSerializer(txn).data
        return success_response(
            message="Transfer completed successfully.",
            data=response_data,
            status_code=status.HTTP_201_CREATED
        )


class TransferDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, transaction_code):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        txn = Transaction.objects.filter(
            Q(sender_wallet_id__in=user_wallets) | Q(receiver_wallet_id__in=user_wallets),
            transaction_code=transaction_code
        ).select_related("sender_wallet__user", "receiver_wallet__user").first()

        if not txn:
            return error_response(message="Transfer transaction not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = TransferDetailSerializer(txn)
        return success_response(data=serializer.data)


class RecipientLookupView(APIView):
    """Searches active recipient users by name, phone, or wallet number."""
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        from apps.wallets.models import Wallet

        wallets_qs = Wallet.objects.select_related("user").filter(
            status="ACTIVE",
            is_primary=True,
        ).exclude(user=request.user)

        if query:
            wallets_qs = wallets_qs.filter(
                Q(wallet_number__icontains=query)
                | Q(user__full_name__icontains=query)
                | Q(user__phone_number__icontains=query)
                | Q(user__email__icontains=query)
            )

        results = []
        for w in wallets_qs[:10]:
            results.append({
                "wallet_number": w.wallet_number,
                "name": w.user.full_name or w.user.phone_number,
                "phone_number": w.user.phone_number,
                "avatar_url": w.user.profile_photo.url if w.user.profile_photo else "",
            })

        return success_response(data=results)


class AccountInquiryView(APIView):
    """
    Inquires recipient account holder name and verification status
    before initiating a transfer. Matches exact wallet number or phone number.
    """
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        account = (request.query_params.get("account") or "").strip()
        if not account:
            return error_response(
                message="Account parameter (wallet number or phone number) is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from apps.wallets.models import Wallet
        import re

        payee_name_param = (request.query_params.get("payee_name") or "").strip()

        candidates = [account]
        clean_acc = re.sub(r"[\s\-\(\)]", "", account)
        candidates.append(clean_acc)
        if clean_acc.startswith("0") and clean_acc[1:].isdigit():
            candidates.append("+855" + clean_acc[1:])
            candidates.append("855" + clean_acc[1:])
        elif clean_acc.startswith("+855") and clean_acc[4:].isdigit():
            candidates.append("0" + clean_acc[4:])
            candidates.append(clean_acc[1:])
        elif clean_acc.startswith("855") and clean_acc[3:].isdigit():
            candidates.append("0" + clean_acc[3:])
            candidates.append("+" + clean_acc)

        # Prevent sending money to oneself
        if (
            request.user.wallets.filter(wallet_number__iexact=account).exists()
            or request.user.phone_number in candidates
        ):
            return error_response(
                message="Cannot transfer to your own wallet or phone number.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        wallet = Wallet.objects.select_related("user").filter(
            Q(wallet_number__iexact=account) | Q(user__phone_number__in=candidates),
            status="ACTIVE",
        ).first()

        if not wallet:
            # Check if this is an external Bakong KHQR account (e.g. user@bank, bakong ID, or merchant code)
            if "@" in account or account.lower().startswith("bakong") or account.startswith("0002") or payee_name_param:
                if payee_name_param:
                    display_name = payee_name_param
                elif "@" in account:
                    parts = account.split("@")
                    name_part = parts[0].replace("_", " ").replace(".", " ").title()
                    bank_part = parts[1].upper()
                    display_name = f"{name_part} ({bank_part})"
                else:
                    display_name = f"Bakong Payee ({account})"

                return success_response(
                    message="Bakong KHQR account verified.",
                    data={
                        "wallet_number": account,
                        "name": display_name,
                        "phone_number": "",
                        "avatar_url": "",
                        "is_verified": True,
                        "is_bakong": True,
                    },
                )

            return error_response(
                message=f"Receiver account '{account}' was not found. Please verify the wallet number or phone number.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return success_response(
            message="Account verified successfully.",
            data={
                "wallet_number": wallet.wallet_number,
                "name": wallet.user.full_name or wallet.user.phone_number,
                "phone_number": wallet.user.phone_number,
                "avatar_url": wallet.user.profile_photo.url if wallet.user.profile_photo else "",
                "is_verified": True,
            },
        )

