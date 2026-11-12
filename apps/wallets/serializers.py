from rest_framework import serializers
from apps.wallets.models import LedgerEntry, Wallet


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = [
            "id",
            "wallet_number",
            "currency",
            "current_balance",
            "available_balance",
            "hold_balance",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class WalletBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = [
            "wallet_number",
            "currency",
            "current_balance",
            "available_balance",
            "hold_balance",
            "status",
        ]
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="transaction.transaction_code", read_only=True)
    transaction_type = serializers.CharField(source="transaction.transaction_type", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "transaction_code",
            "transaction_type",
            "entry_type",
            "amount",
            "balance_before",
            "balance_after",
            "description",
            "created_at",
        ]
        read_only_fields = fields
