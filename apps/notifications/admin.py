from django.contrib import admin
from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "notification_type", "is_read", "read_at", "created_at")
    search_fields = ("title", "message", "user__email", "user__full_name")
    list_filter = ("notification_type", "is_read", "created_at")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "user", "related_transaction", "title", "message", "notification_type", "is_read", "read_at", "created_at", "updated_at")
    actions = ("mark_as_read", "mark_as_unread")

    @admin.action(description="Mark selected notifications as read")
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)

    @admin.action(description="Mark selected notifications as unread")
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)
