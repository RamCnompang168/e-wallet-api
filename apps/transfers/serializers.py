from decimal import Decimal
from rest_framework import serializers
from apps.transactions.models import Transaction


class TransferCreateSerializer(serializers.Serializer):
    receiver_wallet_number = serializers.CharField(required=True, max_length=128)
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=Decimal("0.0001"))
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    reference_number = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    pin = serializers.CharField(required=False, write_only=True, min_length=6, max_length=6)


class TransferDetailSerializer(serializers.ModelSerializer):
    sender_wallet_number = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    receiver_wallet_number = serializers.SerializerMethodField()
    receiver_name = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "transaction_code",
            "transaction_type",
            "status",
            "sender_wallet_number",
            "sender_name",
            "receiver_wallet_number",
            "receiver_name",
            "amount",
            "fee_amount",
            "total_amount",
            "currency",
            "description",
            "reference_number",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_sender_wallet_number(self, obj):
        return obj.sender_wallet.wallet_number if obj.sender_wallet else ""

    def get_sender_name(self, obj):
        return obj.sender_wallet.user.full_name if (obj.sender_wallet and obj.sender_wallet.user) else ""

    def get_receiver_wallet_number(self, obj):
        if obj.receiver_wallet:
            return obj.receiver_wallet.wallet_number
        return (obj.metadata or {}).get("external_account", "")

    def get_receiver_name(self, obj):
        if obj.receiver_wallet and obj.receiver_wallet.user:
            return obj.receiver_wallet.user.full_name
        return (obj.metadata or {}).get("payee_name") or (obj.metadata or {}).get("external_account") or "Bakong Payee"
