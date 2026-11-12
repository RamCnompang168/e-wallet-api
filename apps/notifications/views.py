from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by("-created_at")
        unread_only = request.query_params.get("unread")
        if unread_only and unread_only.lower() == "true":
            notifications = notifications.filter(is_read=False)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(notifications, request)
        serializer = NotificationSerializer(page, many=True)
        resp = paginator.get_paginated_response(serializer.data)
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        resp.data["data"]["unread_count"] = unread_count
        return resp


class UnreadNotificationCountView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return success_response(data={"unread_count": count})


class MarkNotificationReadView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def patch(self, request, pk):
        notification = Notification.objects.filter(id=pk, user=request.user).first()
        if not notification:
            return error_response(message="Notification not found.", status_code=status.HTTP_404_NOT_FOUND)

        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])

        return success_response(
            message="Notification marked as read.",
            data=NotificationSerializer(notification).data
        )


class MarkAllNotificationsReadView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def patch(self, request):
        now = timezone.now()
        updated_count = Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True,
            read_at=now,
            updated_at=now
        )
        return success_response(message=f"Marked {updated_count} notification(s) as read.")
