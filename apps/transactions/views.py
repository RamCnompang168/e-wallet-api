from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser, IsStaffMember
from apps.core.exceptions import BankingException, InvalidTransactionStateException
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.merchants.models import TransactionReversal
from apps.transactions.filters import TransactionFilter
from apps.transactions.models import FeeRule, Transaction, TransactionLimit, TransactionStatus, TransactionType
from apps.transactions.serializers import (
    FeeRuleSerializer,
    TransactionLimitSerializer,
    TransactionListSerializer,
    TransactionReversalActionSerializer,
)
from apps.users.models import AuditLog
from apps.wallets.services import LedgerService


class TransactionListView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        txns = Transaction.objects.filter(
            Q(sender_wallet_id__in=user_wallets) | Q(receiver_wallet_id__in=user_wallets)
        ).select_related("sender_wallet__user", "receiver_wallet__user").order_by("-created_at")

        # Apply django_filters
        filterset = TransactionFilter(request.query_params, queryset=txns)
        if filterset.is_valid():
            txns = filterset.qs

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(txns, request)
        serializer = TransactionListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class TransactionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, transaction_code):
        user_wallets = request.user.wallets.values_list("id", flat=True)
        txn = Transaction.objects.filter(
            Q(sender_wallet_id__in=user_wallets) | Q(receiver_wallet_id__in=user_wallets),
            transaction_code=transaction_code
        ).select_related("sender_wallet__user", "receiver_wallet__user").first()

        if not txn:
            return error_response(message="Transaction not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=TransactionListSerializer(txn, context={"request": request}).data)


class AdminTransactionListView(APIView):
    """Global transaction inspection endpoint for Staff/Admins."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        txns = Transaction.objects.all().select_related("sender_wallet__user", "receiver_wallet__user").order_by("-created_at")
        filterset = TransactionFilter(request.query_params, queryset=txns)
        if filterset.is_valid():
            txns = filterset.qs

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(txns, request)
        serializer = TransactionListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminTransactionReversalView(APIView):
    """Staff/Admin endpoint to execute a full atomic reversal of an erroneous transaction."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def post(self, request, pk):
        serializer = TransactionReversalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data["reason"]

        try:
            orig_txn = Transaction.objects.select_related("sender_wallet", "receiver_wallet").get(id=pk)
        except Transaction.DoesNotExist:
            return error_response(message="Transaction not found.", status_code=status.HTTP_404_NOT_FOUND)

        if orig_txn.status != TransactionStatus.COMPLETED:
            raise InvalidTransactionStateException(f"Only COMPLETED transactions can be reversed (current: {orig_txn.status}).")

        if orig_txn.transaction_type not in [TransactionType.TRANSFER, TransactionType.MERCHANT_PAYMENT]:
            raise BankingException("Only Transfers and Merchant Payments can be reversed via this endpoint.")

        if hasattr(orig_txn, "reversal"):
            raise BankingException("This transaction has already been reversed.")

        with transaction.atomic():
            # Canonical lock
            locked = LedgerService.lock_wallets_canonical(orig_txn.receiver_wallet_id, orig_txn.sender_wallet_id)
            reversal_debtor = locked[str(orig_txn.receiver_wallet_id)]
            reversal_creditor = locked[str(orig_txn.sender_wallet_id)]

            # Create Reversal Transaction
            rev_txn = Transaction.objects.create(
                transaction_type=TransactionType.REVERSAL,
                status=TransactionStatus.PROCESSING,
                sender_wallet=reversal_debtor,
                receiver_wallet=reversal_creditor,
                amount=orig_txn.amount,
                fee_amount=Decimal("0.0000"),
                total_amount=orig_txn.amount,
                currency=orig_txn.currency,
                description=f"Reversal of {orig_txn.transaction_code}: {reason}",
                parent_transaction=orig_txn,
            )

            # Balanced ledger entries
            LedgerService.post_transfer_entries(
                txn=rev_txn,
                sender_wallet=reversal_debtor,
                receiver_wallet=reversal_creditor,
                amount=orig_txn.amount,
                fee_amount=Decimal("0.0000")
            )

            rev_txn.transition_to(TransactionStatus.COMPLETED)
            rev_txn.save(update_fields=["status", "completed_at", "updated_at"])

            reversal_rec = TransactionReversal.objects.create(
                original_transaction=orig_txn,
                reversal_transaction=rev_txn,
                initiated_by=request.user,
                reason=reason,
                status="COMPLETED"
            )

            orig_txn.status = TransactionStatus.REVERSED
            orig_txn.save(update_fields=["status", "updated_at"])

            AuditLog.objects.create(
                user=request.user,
                action="TRANSACTION_REVERSED",
                entity_type="Transaction",
                entity_id=str(orig_txn.id),
                new_value={"reversal_code": reversal_rec.reversal_code, "reason": reason}
            )

        return success_response(
            message="Transaction reversed successfully.",
            data={"reversal_code": reversal_rec.reversal_code, "transaction": TransactionListSerializer(orig_txn).data},
            status_code=status.HTTP_201_CREATED
        )


class AdminLimitsListView(APIView):
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        limits = TransactionLimit.objects.all().order_by("role", "kyc_tier")
        serializer = TransactionLimitSerializer(limits, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        serializer = TransactionLimitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        limit = serializer.save()
        return success_response(data=TransactionLimitSerializer(limit).data, status_code=status.HTTP_201_CREATED)


class AdminFeeRulesListView(APIView):
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        rules = FeeRule.objects.all()
        serializer = FeeRuleSerializer(rules, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        serializer = FeeRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save()
        return success_response(data=FeeRuleSerializer(rule).data, status_code=status.HTTP_201_CREATED)
