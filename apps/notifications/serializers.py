from rest_framework import serializers
from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    transaction_code = serializers.CharField(source="related_transaction.transaction_code", read_only=True, default=None)

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "notification_type",
            "transaction_code",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields
