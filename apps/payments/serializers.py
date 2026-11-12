from decimal import Decimal
from rest_framework import serializers
from apps.payments.models import PaymentMethod, TopUp, Withdrawal


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "method_name", "method_type", "provider_name", "is_active"]
        read_only_fields = fields


class TopUpCreateSerializer(serializers.Serializer):
    payment_method_id = serializers.UUIDField(required=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=Decimal("1.0000"))
    provider_reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)


class TopUpDetailSerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="transaction.transaction_code", read_only=True)
    currency = serializers.CharField(source="transaction.currency", read_only=True)
    payment_method_name = serializers.CharField(source="payment_method.method_name", read_only=True)

    class Meta:
        model = TopUp
        fields = [
            "id",
            "transaction_code",
            "currency",
            "payment_method_name",
            "provider_reference",
            "amount",
            "fee_amount",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class WithdrawalCreateSerializer(serializers.Serializer):
    payment_method_id = serializers.UUIDField(required=True)
    destination_account = serializers.CharField(required=True, max_length=150)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=Decimal("1.0000"))
    pin = serializers.CharField(required=False, write_only=True, min_length=6, max_length=6)


class WithdrawalDetailSerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="transaction.transaction_code", read_only=True)
    currency = serializers.CharField(source="transaction.currency", read_only=True)
    payment_method_name = serializers.CharField(source="payment_method.method_name", read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            "id",
            "transaction_code",
            "currency",
            "payment_method_name",
            "destination_account",
            "provider_reference",
            "amount",
            "fee_amount",
            "status",
            "created_at",
        ]
        read_only_fields = fields
