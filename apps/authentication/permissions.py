from rest_framework import permissions
from apps.users.models import UserRole, UserStatus


class IsActiveUser(permissions.BasePermission):
    """Allows access only to authenticated users whose account status is ACTIVE."""
    message = "Your account is inactive, suspended, or frozen. Access denied."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_active and
            request.user.status == UserStatus.ACTIVE
        )


class IsCustomer(IsActiveUser):
    """Allows access to users with CUSTOMER role."""
    message = "Only customer accounts are authorized for this operation."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.CUSTOMER


class IsMerchant(IsActiveUser):
    """Allows access to registered MERCHANT accounts."""
    message = "Merchant privileges are required for this operation."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.MERCHANT


class IsStaffMember(permissions.BasePermission):
    """Allows access to Staff, Admins, and Super Admins."""
    message = "Staff privileges are required for this action."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.is_staff or request.user.role in [UserRole.STAFF, UserRole.ADMIN, UserRole.SUPER_ADMIN])
        )


class IsAdminUser(permissions.BasePermission):
    """Allows access only to Admin and Super Admin roles."""
    message = "Administrator privileges are required."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
        )


class IsSuperAdmin(permissions.BasePermission):
    """Allows access strictly to Super Administrators."""
    message = "Super Administrator privileges are strictly required."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.role == UserRole.SUPER_ADMIN or request.user.is_superuser)
        )


class HasKYCTier1(IsActiveUser):
    """Allows access only to KYC-verified users (Tier 1 or Tier 2)."""
    message = "KYC identity verification (Tier 1+) is required to access this feature."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.kyc_tier >= 1
