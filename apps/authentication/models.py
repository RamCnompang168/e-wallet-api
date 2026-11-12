import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class OTPPurpose(models.TextChoices):
    REGISTRATION = "REGISTRATION", "User Registration"
    LOGIN = "LOGIN", "Login 2FA"
    TRANSFER = "TRANSFER", "High-Value Transfer Confirmation"
    PASSWORD_RESET = "PASSWORD_RESET", "Password Reset"
    PIN_RESET = "PIN_RESET", "PIN Reset"


def default_otp_expiry():
    return timezone.now() + timedelta(minutes=5)


class OTPCode(BaseModel):
    """Stores one-time passwords for identity, authorization, and 2FA verification."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="otp_codes"
    )
    phone_number = models.CharField(max_length=30, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    otp_code_hash = models.CharField(max_length=255)
    purpose = models.CharField(max_length=30, choices=OTPPurpose.choices, db_index=True)
    expires_at = models.DateTimeField(default=default_otp_expiry)
    verified_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "OTP Code"
        verbose_name_plural = "OTP Codes"
        indexes = [
            models.Index(fields=["phone_number", "purpose", "is_used"]),
            models.Index(fields=["email", "purpose", "is_used"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        dest = self.phone_number or self.email
        return f"OTP for {dest} [{self.purpose}] (Used: {self.is_used})"

    @classmethod
    def create_otp(cls, purpose: str, raw_code: str, user=None, phone_number="", email="", ttl_minutes: int = 5):
        """Hashes OTP and creates record."""
        return cls.objects.create(
            user=user,
            phone_number=phone_number or (user.phone_number if user else ""),
            email=email or (user.email if user else ""),
            otp_code_hash=make_password(raw_code),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes)
        )

    def verify(self, candidate_code: str) -> bool:
        """Verifies candidate code with attempt counting (max 3 tries)."""
        now = timezone.now()
        if self.is_used:
            return False
        if now > self.expires_at:
            return False
        if self.attempt_count >= 3:
            return False

        self.attempt_count += 1
        if check_password(candidate_code, self.otp_code_hash):
            self.is_used = True
            self.verified_at = now
            self.save(update_fields=["attempt_count", "is_used", "verified_at", "updated_at"])
            return True

        self.save(update_fields=["attempt_count", "updated_at"])
        return False
