from django.urls import path
from apps.notifications.views import (
    MarkAllNotificationsReadView,
    MarkNotificationReadView,
    NotificationListView,
    UnreadNotificationCountView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification_list"),
    path("unread-count/", UnreadNotificationCountView.as_view(), name="unread_count"),
    path("read-all/", MarkAllNotificationsReadView.as_view(), name="mark_all_read"),
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="mark_read"),
]
