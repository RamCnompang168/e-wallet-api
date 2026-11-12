from rest_framework import serializers
from apps.kyc.models import DocumentType, KYCDocument, KYCReview, KYCStatus, KYCVerification


class KYCDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCDocument
        fields = [
            "id",
            "document_type",
            "document_number",
            "front_image",
            "back_image",
            "selfie_image",
            "created_at",
        ]
        read_only_fields = fields


class KYCReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.full_name", read_only=True)

    class Meta:
        model = KYCReview
        fields = [
            "id",
            "reviewer_name",
            "decision",
            "rejection_reason",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class KYCVerificationDetailSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    documents = KYCDocumentSerializer(many=True, read_only=True)
    reviews = KYCReviewSerializer(many=True, read_only=True)

    class Meta:
        model = KYCVerification
        fields = [
            "id",
            "user_email",
            "user_name",
            "target_tier",
            "status",
            "documents",
            "reviews",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields


class KYCSubmissionSerializer(serializers.Serializer):
    target_tier = serializers.IntegerField(default=1, min_value=1, max_value=2)
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    document_number = serializers.CharField(required=True, max_length=100)
    front_image = serializers.FileField(required=True)
    back_image = serializers.FileField(required=False)
    selfie_image = serializers.FileField(required=False)


class KYCReviewActionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[KYCStatus.APPROVED, KYCStatus.REJECTED])
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
