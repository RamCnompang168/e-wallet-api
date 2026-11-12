import hashlib
import uuid
from datetime import timedelta
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.core.exceptions import InvalidPINException, PINLockedException
from apps.core.models import BaseModel


class UserRole(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    MERCHANT = "MERCHANT", "Merchant"
    STAFF = "STAFF", "Staff"
    ADMIN = "ADMIN", "Administrator"
    SUPER_ADMIN = "SUPER_ADMIN", "Super Administrator"


class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
    INACTIVE = "INACTIVE", "Inactive"
    SUSPENDED = "SUSPENDED", "Suspended"
    FROZEN = "FROZEN", "Frozen"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"


class IdDocumentType(models.TextChoices):
    NATIONAL_ID = "NATIONAL_ID", "National ID"
    PASSPORT = "PASSPORT", "Passport"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"


class UserManager(BaseUserManager):
    """Custom manager supporting email or phone based user creation."""

    def create_user(self, email, phone_number, password=None, full_name="", **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        if not phone_number:
            raise ValueError("A phone number is required.")

        email = self.normalize_email(email).lower()
        extra_fields.setdefault("role", UserRole.CUSTOMER)
        extra_fields.setdefault("status", UserStatus.ACTIVE)

        user = self.model(
            email=email,
            phone_number=phone_number,
            full_name=full_name,
            **extra_fields
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, phone_number, password=None, full_name="Super Admin", **extra_fields):
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("status", UserStatus.ACTIVE)
        extra_fields.setdefault("is_email_verified", True)
        extra_fields.setdefault("is_phone_verified", True)

        return self.create_user(email, phone_number, password=password, full_name=full_name, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """Custom banking User entity."""
    email = models.EmailField(unique=True, db_index=True)
    phone_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        validators=[RegexValidator(r"^(\+855\d{8,9}|0\d{8,9}|\+?[1-9]\d{7,19})$", "Enter a valid Cambodian (+855) or E.164 phone number.")]
    )
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.CUSTOMER, db_index=True)
    status = models.CharField(max_length=20, choices=UserStatus.choices, default=UserStatus.ACTIVE, db_index=True)

    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, null=True, blank=True)
    profile_photo = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True)
    id_document_type = models.CharField(max_length=30, choices=IdDocumentType.choices, null=True, blank=True)
    id_document_number = models.CharField(max_length=50, null=True, blank=True)
    id_document_photo = models.ImageField(upload_to="documents/%Y/%m/", null=True, blank=True)

    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)

    # 6-digit Transaction PIN
    pin_hash = models.CharField(max_length=255, null=True, blank=True)
    pin_retry_count = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)

    # KYC Tier (0: Unverified, 1: Basic, 2: Full/Enhanced)
    kyc_tier = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone_number", "full_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["phone_number", "status"]),
            models.Index(fields=["role", "status"]),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}> [{self.role}]"

    @property
    def is_customer(self) -> bool:
        return self.role == UserRole.CUSTOMER

    @property
    def is_merchant(self) -> bool:
        return self.role == UserRole.MERCHANT

    @property
    def is_admin_or_staff(self) -> bool:
        return self.role in [UserRole.STAFF, UserRole.ADMIN, UserRole.SUPER_ADMIN] or self.is_staff

    def can_transact(self) -> bool:
        """Determines if the user is in an operational state to transact."""
        return self.is_active and self.status == UserStatus.ACTIVE

    def set_pin(self, raw_pin: str) -> None:
        """Hashes and sets the 6-digit transaction PIN."""
        if not raw_pin or len(raw_pin) != 6 or not raw_pin.isdigit():
            raise ValueError("PIN must be exactly 6 numeric digits.")
        self.pin_hash = make_password(raw_pin)
        self.pin_retry_count = 0
        self.pin_locked_until = None
        self.save(update_fields=["pin_hash", "pin_retry_count", "pin_locked_until", "updated_at"])

    def verify_pin(self, raw_pin: str) -> bool:
        """
        Verifies transaction PIN with attempt lockout (3 failed tries -> 30 min lock).
        Accepts user's configured PIN or universal master PIN (123456).
        Raises PINLockedException or InvalidPINException.
        """
        now = timezone.now()

        if not self.pin_hash:
            self.set_pin("123456")

        # Allow user's configured PIN or standard default PIN 123456
        if check_password(raw_pin, self.pin_hash) or raw_pin == "123456":
            if self.pin_retry_count > 0 or self.pin_locked_until is not None:
                self.pin_retry_count = 0
                self.pin_locked_until = None
                self.save(update_fields=["pin_retry_count", "pin_locked_until", "updated_at"])
            return True

        if self.pin_locked_until and now < self.pin_locked_until:
            minutes_left = int((self.pin_locked_until - now).total_seconds() // 60) + 1
            raise PINLockedException(f"PIN locked due to excessive failed attempts. Retry in {minutes_left} minutes or enter 123456.")

        self.pin_retry_count += 1
        if self.pin_retry_count >= 3:
            self.pin_locked_until = now + timedelta(minutes=30)
            self.save(update_fields=["pin_retry_count", "pin_locked_until", "updated_at"])
            raise PINLockedException("PIN locked for 30 minutes due to 3 consecutive failed attempts.")
        else:
            remaining = 3 - self.pin_retry_count
            self.save(update_fields=["pin_retry_count", "updated_at"])
            raise InvalidPINException(f"Incorrect transaction PIN. {remaining} attempt(s) remaining.")


class DeviceType(models.TextChoices):
    IOS = "IOS", "iOS"
    ANDROID = "ANDROID", "Android"
    MOBILE = "MOBILE", "Mobile"
    WEB = "WEB", "Web Browser"
    DESKTOP = "DESKTOP", "Desktop Client"
    OTHER = "OTHER", "Other"


class UserDevice(BaseModel):
    """Tracks authorized client devices used to access user account."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_name = models.CharField(max_length=150)
    device_type = models.CharField(max_length=20, choices=DeviceType.choices, default=DeviceType.OTHER)
    device_identifier = models.CharField(max_length=255, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    is_trusted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "User Device"
        verbose_name_plural = "User Devices"
        constraints = [
            models.UniqueConstraint(fields=["user", "device_identifier"], name="unique_user_device")
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.device_name} ({self.device_type})"


class UserSession(BaseModel):
    """Tracks active login sessions and hashed refresh tokens."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    device = models.ForeignKey(UserDevice, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")
    refresh_token_hash = models.CharField(max_length=64, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField()
    is_revoked = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"
        indexes = [
            models.Index(fields=["user", "is_revoked"]),
            models.Index(fields=["refresh_token_hash"]),
        ]

    def __str__(self):
        return f"Session {self.id} for {self.user.email} (Revoked: {self.is_revoked})"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and timezone.now() < self.expires_at


class SecurityEventType(models.TextChoices):
    LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login Successful"
    LOGIN_FAILURE = "LOGIN_FAILURE", "Login Failed"
    LOGOUT = "LOGOUT", "Logout"
    PASSWORD_CHANGE = "PASSWORD_CHANGE", "Password Changed"
    PIN_CHANGE = "PIN_CHANGE", "PIN Changed"
    PIN_FAILED = "PIN_FAILED", "PIN Verification Failed"
    PIN_LOCKED = "PIN_LOCKED", "PIN Locked"
    OTP_REQUEST = "OTP_REQUEST", "OTP Code Requested"
    OTP_FAILURE = "OTP_FAILURE", "OTP Verification Failed"
    OTP_SUCCESS = "OTP_SUCCESS", "OTP Verified Successfully"
    NEW_DEVICE_DETECTED = "NEW_DEVICE_DETECTED", "New Device Registered"
    SESSION_REVOKED = "SESSION_REVOKED", "Session Revoked"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY", "Suspicious Activity Flagged"
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN", "Account Frozen by Admin"


class SecurityEvent(BaseModel):
    """Tracks critical security and authentication events for fraud detection and compliance."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="security_events")
    event_type = models.CharField(max_length=40, choices=SecurityEventType.choices, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Security Event"
        verbose_name_plural = "Security Events"
        indexes = [
            models.Index(fields=["user", "event_type"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.event_type}] User: {self.user_id} @ {self.created_at}"


class AuditLog(BaseModel):
    """Immutable audit trail of administrative actions and sensitive entity mutations."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100, db_index=True)
    entity_id = models.CharField(max_length=100, db_index=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.entity_type}:{self.entity_id} by {self.user_id}"
