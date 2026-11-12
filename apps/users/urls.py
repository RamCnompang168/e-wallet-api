from django.urls import path
from apps.users.views import (
    AdminAuditLogsView,
    AdminPendingApprovalsView,
    AdminUserApproveView,
    AdminUserListView,
    AdminUserRejectView,
    AdminUserStatusUpdateView,
    ChangePasswordView,
    ProfilePhotoUploadView,
    RevokeDeviceView,
    SetPINView,
    UserDevicesListView,
    UserProfileView,
    UserSecurityEventsView,
)

app_name = "users"

urlpatterns = [
    # Current User Profile
    path("me/", UserProfileView.as_view(), name="me"),
    path("me/password/", ChangePasswordView.as_view(), name="change_password"),
    path("me/pin/", SetPINView.as_view(), name="set_pin"),
    path("me/profile-photo/", ProfilePhotoUploadView.as_view(), name="profile_photo"),
    path("me/devices/", UserDevicesListView.as_view(), name="devices_list"),
    path("me/devices/<uuid:pk>/", RevokeDeviceView.as_view(), name="revoke_device"),
    path("me/security-events/", UserSecurityEventsView.as_view(), name="security_events"),

    # Admin Management
    path("admin/users/", AdminUserListView.as_view(), name="admin_user_list"),
    path("admin/users/<uuid:pk>/status/", AdminUserStatusUpdateView.as_view(), name="admin_user_status"),
    path("admin/users/<uuid:pk>/approve/", AdminUserApproveView.as_view(), name="admin_user_approve"),
    path("admin/users/<uuid:pk>/reject/", AdminUserRejectView.as_view(), name="admin_user_reject"),
    path("admin/pending-approvals/", AdminPendingApprovalsView.as_view(), name="admin_pending_approvals"),
    path("admin/audit-logs/", AdminAuditLogsView.as_view(), name="admin_audit_logs"),
]
