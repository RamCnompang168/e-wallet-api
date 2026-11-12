from rest_framework import serializers
from apps.beneficiaries.models import Beneficiary
from apps.wallets.models import Wallet


class BeneficiarySerializer(serializers.ModelSerializer):
    wallet_number = serializers.CharField(write_only=True, required=True)
    beneficiary_wallet_number = serializers.CharField(source="beneficiary_wallet.wallet_number", read_only=True)
    beneficiary_name = serializers.CharField(source="beneficiary_wallet.user.full_name", read_only=True)
    beneficiary_currency = serializers.CharField(source="beneficiary_wallet.currency", read_only=True)

    class Meta:
        model = Beneficiary
        fields = [
            "id",
            "wallet_number",
            "beneficiary_wallet_number",
            "beneficiary_name",
            "beneficiary_currency",
            "nickname",
            "is_favorite",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "beneficiary_wallet_number",
            "beneficiary_name",
            "beneficiary_currency",
            "created_at",
            "updated_at",
        ]

    def validate_wallet_number(self, value):
        user = self.context["request"].user
        clean_num = value.strip().upper()
        try:
            target_wallet = Wallet.objects.select_related("user").get(wallet_number=clean_num, status="ACTIVE")
        except Wallet.DoesNotExist:
            raise serializers.ValidationError("Target wallet not found or inactive.")

        if target_wallet.user_id == user.id:
            raise serializers.ValidationError("You cannot add your own wallet as a beneficiary.")

        if Beneficiary.objects.filter(user=user, beneficiary_wallet=target_wallet).exists():
            raise serializers.ValidationError("This wallet is already in your beneficiary list.")

        self.context["target_wallet"] = target_wallet
        return clean_num

    def create(self, validated_data):
        target_wallet = self.context["target_wallet"]
        validated_data.pop("wallet_number", None)
        return Beneficiary.objects.create(
            user=self.context["request"].user,
            beneficiary_wallet=target_wallet,
            **validated_data
        )


class BeneficiaryUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Beneficiary
        fields = ["nickname", "is_favorite"]
