from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.authentication.serializers import UserProfileSerializer
from apps.users.models import SecurityEvent, User, UserDevice


class UserUpdateSerializer(serializers.ModelSerializer):
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "full_name",
            "date_of_birth",
            "gender",
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class SetPINSerializer(serializers.Serializer):
    pin = serializers.CharField(required=True, min_length=6, max_length=6, write_only=True)
    current_pin = serializers.CharField(required=False, min_length=6, max_length=6, write_only=True)

    def validate_pin(self, value):
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("PIN must be exactly 6 numeric digits.")
        return value


class ProfilePhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["profile_photo"]


class UserDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDevice
        fields = [
            "id",
            "device_name",
            "device_type",
            "device_identifier",
            "ip_address",
            "last_login_at",
            "is_trusted",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class SecurityEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityEvent
        fields = [
            "id",
            "event_type",
            "ip_address",
            "user_agent",
            "details",
            "created_at",
        ]
        read_only_fields = fields
