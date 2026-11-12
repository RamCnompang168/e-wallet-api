from rest_framework import serializers
from apps.transactions.models import FeeRule, Transaction, TransactionLimit


class TransactionListSerializer(serializers.ModelSerializer):
    sender_wallet_number = serializers.CharField(source="sender_wallet.wallet_number", read_only=True, default=None)
    receiver_wallet_number = serializers.CharField(source="receiver_wallet.wallet_number", read_only=True, default=None)
    sender_name = serializers.CharField(source="sender_wallet.user.full_name", read_only=True, default="")
    receiver_name = serializers.CharField(source="receiver_wallet.user.full_name", read_only=True, default="")
    sender_user_id = serializers.CharField(source="sender_wallet.user.id", read_only=True, default=None)
    receiver_user_id = serializers.CharField(source="receiver_wallet.user.id", read_only=True, default=None)
    direction = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "transaction_code",
            "transaction_type",
            "status",
            "sender_wallet_number",
            "sender_name",
            "sender_user_id",
            "receiver_wallet_number",
            "receiver_name",
            "receiver_user_id",
            "direction",
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

    def get_direction(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return "UNKNOWN"
        user_wallets = set(request.user.wallets.values_list("id", flat=True))
        is_sender = obj.sender_wallet_id in user_wallets
        is_receiver = obj.receiver_wallet_id in user_wallets
        if is_sender and is_receiver:
            return "SELF"
        if is_receiver:
            return "INCOMING"
        if is_sender:
            return "OUTGOING"
        return "UNKNOWN"


class TransactionLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionLimit
        fields = [
            "id",
            "role",
            "kyc_tier",
            "transaction_type",
            "currency",
            "minimum_amount",
            "maximum_per_transaction",
            "maximum_per_day",
            "maximum_per_month",
            "is_active",
        ]


class FeeRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeRule
        fields = [
            "id",
            "transaction_type",
            "fixed_fee",
            "percentage_fee",
            "min_fee",
            "max_fee",
            "is_active",
        ]


class TransactionReversalActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, max_length=255)
