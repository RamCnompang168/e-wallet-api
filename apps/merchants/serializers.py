from decimal import Decimal
from rest_framework import serializers
from apps.merchants.models import (
    DisputeStatus,
    DisputeType,
    Merchant,
    MerchantPayment,
    Refund,
    TransactionDispute,
)


class MerchantSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = Merchant
        fields = [
            "id",
            "business_name",
            "merchant_code",
            "phone_number",
            "email",
            "status",
            "fee_rate",
            "owner_name",
            "created_at",
        ]
        read_only_fields = ["id", "merchant_code", "status", "fee_rate", "owner_name", "created_at"]


class MerchantRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["business_name", "phone_number", "email"]


class MerchantPaymentCreateSerializer(serializers.Serializer):
    merchant_code = serializers.CharField(required=True, max_length=50)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=Decimal("0.0100"))
    customer_note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    payment_reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    pin = serializers.CharField(required=False, write_only=True, min_length=6, max_length=6)


class MerchantPaymentDetailSerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="transaction.transaction_code", read_only=True)
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    merchant_code = serializers.CharField(source="merchant.merchant_code", read_only=True)
    amount = serializers.DecimalField(source="transaction.amount", max_digits=18, decimal_places=4, read_only=True)
    currency = serializers.CharField(source="transaction.currency", read_only=True)
    status = serializers.CharField(source="transaction.status", read_only=True)

    class Meta:
        model = MerchantPayment
        fields = [
            "id",
            "transaction_code",
            "merchant_name",
            "merchant_code",
            "amount",
            "currency",
            "status",
            "payment_reference",
            "customer_note",
            "created_at",
        ]
        read_only_fields = fields


class RefundCreateSerializer(serializers.Serializer):
    original_transaction_id = serializers.UUIDField(required=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=Decimal("0.0100"))
    reason = serializers.CharField(required=True, max_length=255)


class RefundDetailSerializer(serializers.ModelSerializer):
    original_transaction_code = serializers.CharField(source="original_transaction.transaction_code", read_only=True)
    refund_transaction_code = serializers.CharField(source="refund_transaction.transaction_code", read_only=True)
    currency = serializers.CharField(source="original_transaction.currency", read_only=True)

    class Meta:
        model = Refund
        fields = [
            "id",
            "refund_code",
            "original_transaction_code",
            "refund_transaction_code",
            "amount",
            "currency",
            "reason",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class DisputeCreateSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField(required=True)
    dispute_type = serializers.ChoiceField(choices=DisputeType.choices)
    reason = serializers.CharField(required=True)
    evidence_file = serializers.FileField(required=False)


class DisputeDetailSerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="transaction.transaction_code", read_only=True)
    claimant_name = serializers.CharField(source="claimant.full_name", read_only=True)
    reviewer_name = serializers.CharField(source="reviewer.full_name", read_only=True, default=None)

    class Meta:
        model = TransactionDispute
        fields = [
            "id",
            "dispute_code",
            "transaction_code",
            "claimant_name",
            "dispute_type",
            "reason",
            "status",
            "evidence_file",
            "resolution_notes",
            "reviewer_name",
            "resolved_at",
            "created_at",
        ]
        read_only_fields = fields


class DisputeResolveSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[DisputeStatus.ACCEPTED, DisputeStatus.REJECTED])
    resolution_notes = serializers.CharField(required=True)
