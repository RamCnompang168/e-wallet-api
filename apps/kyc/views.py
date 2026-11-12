from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser, IsStaffMember
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.kyc.models import KYCStatus, KYCVerification
from apps.kyc.serializers import (
    KYCReviewActionSerializer,
    KYCSubmissionSerializer,
    KYCVerificationDetailSerializer,
)
from apps.kyc.services import KYCService


class KYCListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]
    parser_classes = [MultiPartParser]

    def get(self, request):
        submissions = KYCVerification.objects.filter(user=request.user).prefetch_related("documents", "reviews").order_by("-created_at")
        serializer = KYCVerificationDetailSerializer(submissions, many=True)
        return success_response(data=serializer.data)

    def post(self, request):
        serializer = KYCSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification = KYCService.submit_kyc_application(
            user=request.user,
            target_tier=serializer.validated_data["target_tier"],
            document_type=serializer.validated_data["document_type"],
            document_number=serializer.validated_data["document_number"],
            front_image=request.FILES.get("front_image"),
            back_image=request.FILES.get("back_image"),
            selfie_image=request.FILES.get("selfie_image")
        )

        return success_response(
            message="KYC application submitted successfully and is pending compliance review.",
            data=KYCVerificationDetailSerializer(verification).data,
            status_code=status.HTTP_201_CREATED
        )


class KYCStatusView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        latest = KYCVerification.objects.filter(user=request.user).order_by("-created_at").first()
        data = {
            "current_tier": request.user.kyc_tier,
            "application_status": latest.status if latest else "NOT_SUBMITTED",
            "last_submitted_at": latest.created_at if latest else None,
            "completed_at": latest.completed_at if latest else None,
        }
        return success_response(data=data)


class AdminKYCQueueView(APIView):
    """Staff/Admin queue of pending and historical KYC verifications."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        submissions = KYCVerification.objects.all().select_related("user").prefetch_related("documents", "reviews").order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            submissions = submissions.filter(status=status_filter.upper())

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(submissions, request)
        serializer = KYCVerificationDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminKYCReviewView(APIView):
    """Staff/Admin endpoint to approve or reject a KYC verification application."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def patch(self, request, pk):
        serializer = KYCReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification = KYCService.review_kyc_application(
            reviewer=request.user,
            verification_id=str(pk),
            decision=serializer.validated_data["decision"],
            rejection_reason=serializer.validated_data.get("rejection_reason", ""),
            notes=serializer.validated_data.get("notes", "")
        )

        return success_response(
            message=f"KYC application has been {verification.status.lower()}.",
            data=KYCVerificationDetailSerializer(verification).data
        )
