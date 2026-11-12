from rest_framework import serializers
from apps.settlement.models import ReconciliationBatch, ReconciliationRecord, WebhookEvent


class WebhookPayloadSerializer(serializers.Serializer):
    event_id = serializers.CharField(required=True)
    event_type = serializers.CharField(required=True)
    data = serializers.DictField(required=True)


class ReconciliationRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconciliationRecord
        fields = [
            "id",
            "external_reference",
            "internal_amount",
            "external_amount",
            "status",
            "discrepancy_details",
            "created_at",
        ]
        read_only_fields = fields


class ReconciliationBatchSerializer(serializers.ModelSerializer):
    records = ReconciliationRecordSerializer(many=True, read_only=True)

    class Meta:
        model = ReconciliationBatch
        fields = [
            "id",
            "batch_code",
            "provider",
            "reconciliation_date",
            "total_internal_records",
            "total_external_records",
            "matched_count",
            "mismatch_count",
            "status",
            "records",
            "created_at",
        ]
        read_only_fields = fields


class RunReconciliationSerializer(serializers.Serializer):
    provider = serializers.CharField(required=True)
    reconciliation_date = serializers.DateField(required=True)
    external_records = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        help_text="List of external statement records: [{'reference': '...', 'amount': '...'}]"
    )
