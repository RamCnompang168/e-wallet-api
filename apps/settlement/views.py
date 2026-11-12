from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsStaffMember
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.settlement.models import ReconciliationBatch, WebhookEvent
from apps.settlement.serializers import (
    ReconciliationBatchSerializer,
    RunReconciliationSerializer,
    WebhookPayloadSerializer,
)
from apps.settlement.services import ReconciliationService, WebhookService


class WebhookReceiverView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, provider):
        serializer = WebhookPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sig = request.headers.get("X-Signature", "") or request.META.get("HTTP_X_SIGNATURE", "")

        event = WebhookService.record_and_process_webhook(
            provider=provider.upper(),
            external_event_id=serializer.validated_data["event_id"],
            event_type=serializer.validated_data["event_type"],
            payload=serializer.validated_data["data"],
            signature=sig
        )

        return success_response(
            message="Webhook received and processed.",
            data={"event_id": event.external_event_id, "status": event.status}
        )


class ReconciliationListView(APIView):
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        batches = ReconciliationBatch.objects.all().order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(batches, request)
        serializer = ReconciliationBatchSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ReconciliationRunView(APIView):
    permission_classes = [IsAuthenticated, IsStaffMember]

    def post(self, request):
        serializer = RunReconciliationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        batch = ReconciliationService.run_reconciliation(
            provider=serializer.validated_data["provider"],
            recon_date=serializer.validated_data["reconciliation_date"],
            external_records=serializer.validated_data["external_records"]
        )

        return success_response(
            message=f"Reconciliation batch {batch.batch_code} finished with status {batch.status}.",
            data=ReconciliationBatchSerializer(batch).data,
            status_code=status.HTTP_201_CREATED
        )


class ReconciliationDetailView(APIView):
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request, batch_code):
        batch = ReconciliationBatch.objects.filter(batch_code=batch_code).prefetch_related("records").first()
        if not batch:
            return error_response(message="Reconciliation batch not found.", status_code=status.HTTP_404_NOT_FOUND)

        return success_response(data=ReconciliationBatchSerializer(batch).data)
