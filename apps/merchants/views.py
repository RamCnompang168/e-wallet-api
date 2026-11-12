from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser, IsStaffMember
from apps.core.idempotency import idempotent_request
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.merchants.models import Merchant, MerchantPayment, MerchantStatus, Refund, TransactionDispute
from apps.merchants.serializers import (
    DisputeCreateSerializer,
    DisputeDetailSerializer,
    DisputeResolveSerializer,
    MerchantPaymentCreateSerializer,
    MerchantPaymentDetailSerializer,
    MerchantRegisterSerializer,
    MerchantSerializer,
    RefundCreateSerializer,
    RefundDetailSerializer,
)
from apps.merchants.services import DisputeService, MerchantPaymentService, RefundService
from apps.users.models import UserRole


class MerchantListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsActiveUser()]
        return [AllowAny()]

    def get(self, request):
        merchants = Merchant.objects.filter(status=MerchantStatus.ACTIVE).select_related("owner").order_by("business_name")
        search = request.query_params.get("search")
        if search:
            merchants = merchants.filter(
                Q(business_name__icontains=search) | Q(merchant_code__icontains=search)
            )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(merchants, request)
        serializer = MerchantSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if hasattr(request.user, "merchant_profile"):
            return error_response(message="User already has a registered merchant profile.")

        serializer = MerchantRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        merchant = Merchant.objects.create(
            owner=request.user,
            **serializer.validated_data
        )

        request.user.role = UserRole.MERCHANT
        request.user.save(update_fields=["role", "updated_at"])

        return success_response(
            message="Merchant profile registered successfully.",
            data=MerchantSerializer(merchant).data,
            status_code=status.HTTP_201_CREATED
        )


class MerchantDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, code):
        merchant = Merchant.objects.filter(merchant_code=code.strip().upper(), status=MerchantStatus.ACTIVE).first()
        if not merchant:
            return error_response(message="Merchant not found.", status_code=status.HTTP_404_NOT_FOUND)
        return success_response(data=MerchantSerializer(merchant).data)


class MerchantPaymentListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user = request.user
        payments = MerchantPayment.objects.filter(
            Q(transaction__sender_wallet__user=user) | Q(merchant__owner=user)
        ).select_related("transaction", "merchant").order_by("-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(payments, request)
        serializer = MerchantPaymentDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @idempotent_request()
    def post(self, request):
        serializer = MerchantPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_pin = (
            serializer.validated_data.get("pin")
            or request.headers.get("x-transaction-pin")
            or request.META.get("HTTP_X_TRANSACTION_PIN")
        )

        txn = MerchantPaymentService.execute_merchant_payment(
            customer_user=request.user,
            merchant_code=serializer.validated_data["merchant_code"],
            amount=serializer.validated_data["amount"],
            customer_note=serializer.validated_data.get("customer_note", ""),
            payment_reference=serializer.validated_data.get("payment_reference", ""),
            pin=raw_pin
        )

        payment_rec = txn.merchant_payment_details
        return success_response(
            message="Merchant payment completed successfully.",
            data=MerchantPaymentDetailSerializer(payment_rec).data,
            status_code=status.HTTP_201_CREATED
        )


class MerchantPaymentDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, pk):
        user = request.user
        payment = MerchantPayment.objects.filter(
            Q(transaction__sender_wallet__user=user) | Q(merchant__owner=user),
            id=pk
        ).select_related("transaction", "merchant").first()

        if not payment:
            return error_response(message="Merchant payment not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=MerchantPaymentDetailSerializer(payment).data)


class RefundListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        user = request.user
        refunds = Refund.objects.filter(
            Q(original_transaction__sender_wallet__user=user) |
            Q(original_transaction__receiver_wallet__user=user) |
            Q(merchant__owner=user)
        ).select_related("original_transaction", "refund_transaction").order_by("-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(refunds, request)
        serializer = RefundDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @idempotent_request()
    def post(self, request):
        serializer = RefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refund_rec = RefundService.process_refund(
            initiator_user=request.user,
            original_transaction_id=str(serializer.validated_data["original_transaction_id"]),
            amount=serializer.validated_data["amount"],
            reason=serializer.validated_data["reason"]
        )

        return success_response(
            message="Refund processed successfully.",
            data=RefundDetailSerializer(refund_rec).data,
            status_code=status.HTTP_201_CREATED
        )


class RefundDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, pk):
        user = request.user
        refund = Refund.objects.filter(
            Q(original_transaction__sender_wallet__user=user) |
            Q(original_transaction__receiver_wallet__user=user) |
            Q(merchant__owner=user),
            id=pk
        ).select_related("original_transaction", "refund_transaction").first()

        if not refund:
            return error_response(message="Refund record not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=RefundDetailSerializer(refund).data)


class DisputeListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        disputes = TransactionDispute.objects.filter(claimant=request.user).select_related("transaction", "claimant").order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(disputes, request)
        serializer = DisputeDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = DisputeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dispute = DisputeService.file_dispute(
            user=request.user,
            transaction_id=str(serializer.validated_data["transaction_id"]),
            dispute_type=serializer.validated_data["dispute_type"],
            reason=serializer.validated_data["reason"],
            evidence_file=request.FILES.get("evidence_file")
        )

        return success_response(
            message="Dispute filed successfully.",
            data=DisputeDetailSerializer(dispute).data,
            status_code=status.HTTP_201_CREATED
        )


class DisputeDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request, pk):
        dispute = TransactionDispute.objects.filter(id=pk, claimant=request.user).select_related("transaction", "claimant", "reviewer").first()
        if not dispute:
            return error_response(message="Dispute not found.", status_code=status.HTTP_404_NOT_FOUND)
        return success_response(data=DisputeDetailSerializer(dispute).data)


class DisputeResolveView(APIView):
    """Staff/Admin resolution endpoint for disputes."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def patch(self, request, pk):
        serializer = DisputeResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resolved_dispute = DisputeService.resolve_dispute(
            reviewer_user=request.user,
            dispute_id=str(pk),
            decision=serializer.validated_data["decision"],
            resolution_notes=serializer.validated_data["resolution_notes"]
        )

        return success_response(
            message=f"Dispute {resolved_dispute.dispute_code} has been resolved as {resolved_dispute.status}.",
            data=DisputeDetailSerializer(resolved_dispute).data
        )
