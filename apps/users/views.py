from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.permissions import IsActiveUser, IsStaffMember
from apps.authentication.serializers import UserProfileSerializer
from apps.authentication.views import get_client_ip
from apps.core.pagination import StandardResultsSetPagination
from apps.core.responses import error_response, success_response
from apps.users.models import AuditLog, SecurityEvent, SecurityEventType, User, UserDevice, UserStatus
from apps.users.serializers import (
    ChangePasswordSerializer,
    ProfilePhotoSerializer,
    SecurityEventSerializer,
    SetPINSerializer,
    UserDeviceSerializer,
    UserUpdateSerializer,
)


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return success_response(data=serializer.data)

    def patch(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message="Profile updated successfully.",
            data=UserProfileSerializer(request.user).data
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def patch(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(old_password):
            return error_response(message="Current password is incorrect.", status_code=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])

        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.PASSWORD_CHANGE,
            ip_address=get_client_ip(request),
            details={"action": "password_changed_by_user"}
        )
        return success_response(message="Password changed successfully.")


class SetPINView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def post(self, request):
        serializer = SetPINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_pin = serializer.validated_data.get("current_pin")
        new_pin = serializer.validated_data["pin"]

        if user.pin_hash:
            if not current_pin:
                return error_response(
                    message="Current PIN is required to set a new PIN.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            user.verify_pin(current_pin)

        user.set_pin(new_pin)

        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.PIN_CHANGE,
            ip_address=get_client_ip(request),
            details={"action": "pin_updated"}
        )
        return success_response(message="Transaction PIN updated successfully.")


class ProfilePhotoUploadView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = ProfilePhotoSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            message="Profile photo uploaded successfully.",
            data={"profile_photo_url": request.user.profile_photo.url if request.user.profile_photo else None}
        )


class UserDevicesListView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        devices = UserDevice.objects.filter(user=request.user, is_active=True).order_by("-last_login_at")
        serializer = UserDeviceSerializer(devices, many=True)
        return success_response(data=serializer.data)


class RevokeDeviceView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def delete(self, request, pk):
        device = UserDevice.objects.filter(id=pk, user=request.user).first()
        if not device:
            return error_response(message="Device not found.", status_code=status.HTTP_404_NOT_FOUND)

        device.is_active = False
        device.save(update_fields=["is_active", "updated_at"])

        # Invalidate all active sessions for this device
        device.sessions.filter(is_revoked=False).update(is_revoked=True)

        SecurityEvent.objects.create(
            user=request.user,
            event_type=SecurityEventType.SESSION_REVOKED,
            ip_address=get_client_ip(request),
            details={"device_id": str(device.id)}
        )
        return success_response(message="Device and associated sessions revoked successfully.")


class UserSecurityEventsView(APIView):
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        events = SecurityEvent.objects.filter(user=request.user).order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(events, request)
        serializer = SecurityEventSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminUserListView(APIView):
    """Staff/Admin view to query all registered users."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        users = User.objects.all().order_by("-created_at")
        role = request.query_params.get("role")
        user_status = request.query_params.get("status")
        if role:
            users = users.filter(role=role.upper())
        if user_status:
            users = users.filter(status=user_status.upper())

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = UserProfileSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminUserStatusUpdateView(APIView):
    """Staff/Admin view to change account status (e.g. FROZEN, ACTIVE, SUSPENDED)."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def patch(self, request, pk):
        new_status = request.data.get("status")
        if not new_status or new_status.upper() not in UserStatus.values:
            return error_response(
                message=f"Valid status required: {UserStatus.values}",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(id=pk).first()
        if not user:
            return error_response(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

        old_status = user.status
        user.status = new_status.upper()
        user.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            user=request.user,
            action="ADMIN_UPDATE_USER_STATUS",
            entity_type="User",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": user.status}
        )

        return success_response(
            message=f"User status updated from {old_status} to {user.status}.",
            data=UserProfileSerializer(user).data
        )


class AdminAuditLogsView(APIView):
    """Staff/Admin view to inspect immutable audit trail."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        logs = AuditLog.objects.all().order_by("-created_at")
        entity_type = request.query_params.get("entity_type")
        if entity_type:
            logs = logs.filter(entity_type=entity_type)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(logs, request)
        data = [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "ip_address": log.ip_address,
                "created_at": log.created_at,
            }
            for log in page
        ]
        return paginator.get_paginated_response(data)


class AdminPendingApprovalsView(APIView):
    """Staff/Admin view to list all registration accounts waiting for approval."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        pending_users = User.objects.filter(status=UserStatus.PENDING_APPROVAL).order_by("-created_at")
        results = []
        for u in pending_users:
            doc_photo_url = request.build_absolute_uri(u.id_document_photo.url) if u.id_document_photo else None
            avatar_url = request.build_absolute_uri(u.profile_photo.url) if u.profile_photo else None
            results.append({
                "id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone_number": u.phone_number,
                "id_document_type": u.id_document_type or "NATIONAL_ID",
                "id_document_number": u.id_document_number or "",
                "id_document_photo": doc_photo_url,
                "profile_photo": avatar_url,
                "gender": u.gender or "",
                "date_of_birth": str(u.date_of_birth) if u.date_of_birth else "",
                "status": u.status,
                "created_at": u.created_at.isoformat() if u.created_at else "",
            })
        return success_response(data=results)


class AdminUserApproveView(APIView):
    """Staff/Admin endpoint to approve and activate a user account."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def post(self, request, pk):
        user = User.objects.filter(id=pk).first()
        if not user:
            return error_response(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

        old_status = user.status
        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.kyc_tier = max(user.kyc_tier, 1)
        user.save(update_fields=["status", "is_active", "kyc_tier", "updated_at"])

        # Activate primary wallet
        from apps.wallets.models import Wallet
        Wallet.objects.filter(user=user, is_primary=True).update(status="ACTIVE")

        # Notify the approved user
        try:
            from apps.notifications.models import NotificationType
            from apps.notifications.services import NotificationService
            NotificationService.create_notification(
                user=user,
                title="Account Approved! 🎉",
                message="Your account registration has been verified and approved by NovaPay operations. You can now use all wallet features!",
                notification_type=NotificationType.SYSTEM,
            )
        except Exception:
            pass

        AuditLog.objects.create(
            user=request.user,
            action="ADMIN_APPROVE_USER",
            entity_type="User",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": user.status},
            ip_address=get_client_ip(request),
        )

        return success_response(
            message=f"Account for {user.full_name} has been approved successfully.",
            data=UserProfileSerializer(user).data
        )


class AdminUserRejectView(APIView):
    """Staff/Admin endpoint to reject a pending user registration."""
    permission_classes = [IsAuthenticated, IsStaffMember]

    def post(self, request, pk):
        user = User.objects.filter(id=pk).first()
        if not user:
            return error_response(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

        reason = request.data.get("reason", "Identity document could not be verified.")
        old_status = user.status
        user.status = UserStatus.REJECTED
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])

        AuditLog.objects.create(
            user=request.user,
            action="ADMIN_REJECT_USER",
            entity_type="User",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": user.status, "reason": reason},
            ip_address=get_client_ip(request),
        )

        return success_response(
            message=f"Registration for {user.full_name} has been rejected.",
            data={"id": str(user.id), "status": user.status, "reason": reason}
        )

