from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser
from apps.beneficiaries.models import Beneficiary
from apps.beneficiaries.serializers import BeneficiarySerializer, BeneficiaryUpdateSerializer
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response


class BeneficiaryListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        beneficiaries = Beneficiary.objects.filter(user=request.user).select_related("beneficiary_wallet__user").order_by("-is_favorite", "nickname")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(beneficiaries, request)
        serializer = BeneficiarySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = BeneficiarySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        beneficiary = serializer.save()
        return success_response(
            message="Beneficiary added successfully.",
            data=BeneficiarySerializer(beneficiary).data,
            status_code=status.HTTP_201_CREATED
        )


class BeneficiaryDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def patch(self, request, pk):
        beneficiary = Beneficiary.objects.filter(id=pk, user=request.user).first()
        if not beneficiary:
            return error_response(message="Beneficiary not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = BeneficiaryUpdateSerializer(beneficiary, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message="Beneficiary updated successfully.",
            data=BeneficiarySerializer(beneficiary).data
        )

    def delete(self, request, pk):
        beneficiary = Beneficiary.objects.filter(id=pk, user=request.user).first()
        if not beneficiary:
            return error_response(message="Beneficiary not found.", status_code=status.HTTP_404_NOT_FOUND)

        beneficiary.delete()
        return success_response(message="Beneficiary removed successfully.")
