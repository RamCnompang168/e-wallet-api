from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from rest_framework import serializers

from apps.authentication.models import OTPPurpose
from apps.users.models import DeviceType, Gender, User, UserRole, UserStatus


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={"input_type": "password"})
    pin = serializers.CharField(write_only=True, required=False, min_length=6, max_length=6)
    phone_number = serializers.CharField(max_length=30, required=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    id_document_type = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    id_document_number = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    id_document_photo = serializers.ImageField(required=False, allow_null=True)
    profile_photo = serializers.ImageField(required=False, allow_null=True)
    id_document_photo_base64 = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    profile_photo_base64 = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone_number",
            "full_name",
            "password",
            "pin",
            "role",
            "date_of_birth",
            "gender",
            "id_document_type",
            "id_document_number",
            "id_document_photo",
            "profile_photo",
            "id_document_photo_base64",
            "profile_photo_base64",
        ]
        read_only_fields = ["id"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_phone_number(self, value):
        import re
        val = re.sub(r"[\s\-\(\)]", "", value)
        # Normalize local Cambodian format (e.g., 012345678, 0881234567 -> +855...)
        if re.match(r"^0\d{8,9}$", val):
            val = "+855" + val[1:]
        elif re.match(r"^855\d{8,9}$", val):
            val = "+" + val
        elif not re.match(r"^\+855\d{8,9}$", val) and not re.match(r"^\+[1-9]\d{7,19}$", val):
            raise serializers.ValidationError(
                "Enter a valid Cambodian phone number (e.g. 012 345 678, 088 123 4567, or +855 12 345 678)."
            )
        alt_val = "0" + val[4:] if val.startswith("+855") else ("+855" + val[1:] if val.startswith("0") else val)
        if User.objects.filter(Q(phone_number=val) | Q(phone_number=alt_val)).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return val

    def validate_pin(self, value):
        if value and (not value.isdigit() or len(value) != 6):
            raise serializers.ValidationError("Transaction PIN must be exactly 6 numeric digits.")
        return value

    def validate_role(self, value):
        # Public registration only permits CUSTOMER and MERCHANT roles
        if value not in [UserRole.CUSTOMER, UserRole.MERCHANT]:
            raise serializers.ValidationError("Only Customer or Merchant accounts can be registered publicly.")
        return value


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True, help_text="Email or phone number")
    password = serializers.CharField(required=True, write_only=True, style={"input_type": "password"})
    device_identifier = serializers.CharField(required=False, default="")
    device_name = serializers.CharField(required=False, default="Mobile/Browser")
    device_type = serializers.ChoiceField(choices=DeviceType.choices, default=DeviceType.OTHER)


class RefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)


class SendOTPSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=OTPPurpose.choices, default=OTPPurpose.LOGIN)
    phone_number = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("phone_number") and not attrs.get("email"):
            raise serializers.ValidationError("Either phone_number or email must be provided.")
        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)
    code = serializers.CharField(required=True, min_length=6, max_length=6)
    phone_number = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("phone_number") and not attrs.get("email"):
            raise serializers.ValidationError("Either phone_number or email must be provided.")
        if not attrs["code"].isdigit():
            raise serializers.ValidationError("Code must be 6 numeric digits.")
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True, help_text="Registered email or phone number")


class ResetPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True, help_text="Registered email or phone number")
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone_number",
            "full_name",
            "role",
            "status",
            "is_email_verified",
            "is_phone_verified",
            "date_of_birth",
            "gender",
            "profile_photo",
            "id_document_type",
            "id_document_number",
            "id_document_photo",
            "kyc_tier",
            "last_login_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "email",
            "phone_number",
            "role",
            "status",
            "is_email_verified",
            "is_phone_verified",
            "kyc_tier",
            "last_login_at",
            "created_at",
        ]
