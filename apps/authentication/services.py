import logging
import secrets
from datetime import timedelta
from typing import Dict, Optional, Tuple
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import OTPCode, OTPPurpose
from apps.users.models import (
    AuditLog,
    DeviceType,
    SecurityEvent,
    SecurityEventType,
    User,
    UserDevice,
    UserRole,
    UserSession,
    UserStatus,
)

logger = logging.getLogger("banking.auth")


class OTPService:
    """Handles secure OTP code generation, dispatching, and verification."""

    @classmethod
    def generate_otp(
        cls,
        purpose: str,
        user: Optional[User] = None,
        phone_number: str = "",
        email: str = "",
        ttl_minutes: int = 5,
        ip_address: Optional[str] = None
    ) -> Tuple[OTPCode, str]:
        raw_code = "".join(secrets.choice("0123456789") for _ in range(6))

        # Invalidate prior pending OTPs for this destination & purpose
        prior_query = OTPCode.objects.filter(purpose=purpose, is_used=False)
        if phone_number:
            prior_query = prior_query.filter(phone_number=phone_number)
        elif email:
            prior_query = prior_query.filter(email=email)
        elif user:
            prior_query = prior_query.filter(user=user)
        prior_query.update(is_used=True)

        otp_record = OTPCode.create_otp(
            purpose=purpose,
            raw_code=raw_code,
            user=user,
            phone_number=phone_number or (user.phone_number if user else ""),
            email=email or (user.email if user else ""),
            ttl_minutes=ttl_minutes
        )

        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.OTP_REQUEST,
            ip_address=ip_address,
            details={"purpose": purpose, "destination": phone_number or email}
        )

        # Dispatch real email if an email destination is specified
        if email:
            cls._dispatch_email_otp(email=email, purpose=purpose, raw_code=raw_code, ttl_minutes=ttl_minutes)
        else:
            logger.info("SIMULATED OTP DISPATCH: Destination=%s Purpose=%s Code=%s", phone_number, purpose, raw_code)
            print(f"[OTP SIMULATION] >>> Sent {purpose} code: {raw_code} to {phone_number} <<<")

        return otp_record, raw_code

    @classmethod
    def _dispatch_email_otp(cls, email: str, purpose: str, raw_code: str, ttl_minutes: int) -> None:
        """Sends real 6-digit OTP email via Django configured SMTP backend with fallback to console."""
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings

        clean_purpose = purpose.replace("_", " ").title()
        subject = f"NovaPay: Your {clean_purpose} Verification Code is {raw_code}"
        text_content = (
            f"Hello,\n\n"
            f"Your NovaPay 6-digit verification code is: {raw_code}\n\n"
            f"This code will expire in {ttl_minutes} minutes.\n"
            f"If you did not request this verification, please ignore this email.\n\n"
            f"— NovaPay Digital Wallet Security Team"
        )
        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 16px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 24px;">
                <h2 style="color: #047857; margin: 0; font-size: 24px; font-weight: 800;">NovaPay Wallet</h2>
                <p style="color: #64748b; font-size: 14px; margin: 4px 0 0 0;">Secure Digital Wallet &amp; Banking</p>
            </div>
            <div style="padding: 20px; background-color: #f8fafc; border-radius: 12px; border: 1px solid #edf2f7; text-align: center;">
                <p style="color: #334155; font-size: 15px; margin: 0 0 16px 0; font-weight: 600;">Your Email Verification Code:</p>
                <div style="background-color: #ecfdf5; border: 2px dashed #10b981; border-radius: 10px; padding: 14px 24px; display: inline-block;">
                    <span style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #065f46; font-family: monospace;">{raw_code}</span>
                </div>
                <p style="color: #64748b; font-size: 13px; margin: 16px 0 0 0;">Valid for <strong>{ttl_minutes} minutes</strong>. Do not share this code with anyone.</p>
            </div>
            <div style="margin-top: 24px; text-align: center; color: #94a3b8; font-size: 12px; line-height: 1.5;">
                <p style="margin: 0;">If you didn't request this email, you can safely ignore it.</p>
                <p style="margin: 4px 0 0 0;">&copy; 2026 NovaPay Cambodia. All rights reserved.</p>
            </div>
        </div>
        """

        try:
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "NovaPay Wallet <noreply@novapay.com>")
            msg = EmailMultiAlternatives(subject, text_content, from_email, [email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
            logger.info("Real OTP email sent via SMTP to %s", email)
            print(f"[REAL EMAIL SENT] >>> Successfully dispatched 6-digit OTP to {email} <<<")
        except Exception as e:
            logger.warning("Could not send real email via SMTP: %s. Falling back to log simulation.", e)
            print(f"[OTP FALLBACK] Failed to send email via SMTP to {email}: {e}")

    @classmethod
    def verify_otp(
        cls,
        purpose: str,
        code: str,
        user: Optional[User] = None,
        phone_number: str = "",
        email: str = "",
        ip_address: Optional[str] = None
    ) -> bool:
        query = OTPCode.objects.filter(
            purpose=purpose,
            is_used=False,
            expires_at__gt=timezone.now()
        ).order_by("-created_at")

        if phone_number:
            query = query.filter(phone_number=phone_number)
        elif email:
            query = query.filter(email=email)
        elif user:
            query = query.filter(user=user)
        else:
            raise ValidationError("A user, phone number, or email destination is required.")

        otp_record = query.first()
        if not otp_record:
            SecurityEvent.objects.create(
                user=user,
                event_type=SecurityEventType.OTP_FAILURE,
                ip_address=ip_address,
                details={"purpose": purpose, "reason": "No active OTP found or expired"}
            )
            raise ValidationError("Invalid or expired OTP code. Please request a new one.")

        is_valid = otp_record.verify(code)
        if not is_valid:
            SecurityEvent.objects.create(
                user=user,
                event_type=SecurityEventType.OTP_FAILURE,
                ip_address=ip_address,
                details={"purpose": purpose, "attempts": otp_record.attempt_count}
            )
            raise ValidationError("Incorrect OTP code. Please verify and try again.")

        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.OTP_SUCCESS,
            ip_address=ip_address,
            details={"purpose": purpose}
        )
        return True


class AuthService:
    """Manages user registration, JWT generation, device tracking, and session rotation."""

    @classmethod
    @transaction.atomic
    def register_user(cls, validated_data: dict, ip_address: Optional[str] = None, user_agent: str = "") -> Tuple[User, Dict]:
        password = validated_data.pop("password", None)
        role = validated_data.get("role", UserRole.CUSTOMER)
        pin = validated_data.pop("pin", None)
        profile_photo_b64 = validated_data.pop("profile_photo_base64", None)
        id_doc_photo_b64 = validated_data.pop("id_document_photo_base64", None)
        profile_photo_file = validated_data.pop("profile_photo", None)
        id_doc_photo_file = validated_data.pop("id_document_photo", None)

        user = User.objects.create_user(
            email=validated_data["email"],
            phone_number=validated_data["phone_number"],
            full_name=validated_data["full_name"],
            password=password,
            role=role,
            status=validated_data.get("status", UserStatus.PENDING_APPROVAL),
            date_of_birth=validated_data.get("date_of_birth"),
            gender=validated_data.get("gender"),
            id_document_type=validated_data.get("id_document_type"),
            id_document_number=validated_data.get("id_document_number"),
            kyc_tier=1,
        )

        import base64
        import uuid
        from django.core.files.base import ContentFile

        if profile_photo_file:
            user.profile_photo = profile_photo_file
        elif profile_photo_b64:
            try:
                b64_data = profile_photo_b64.split(",")[1] if "," in profile_photo_b64 else profile_photo_b64
                decoded = base64.b64decode(b64_data)
                user.profile_photo.save(f"avatar_{uuid.uuid4().hex[:8]}.jpg", ContentFile(decoded), save=False)
            except Exception as e:
                logger.warning("Failed to decode profile_photo_base64: %s", e)

        if id_doc_photo_file:
            user.id_document_photo = id_doc_photo_file
        elif id_doc_photo_b64:
            try:
                b64_data = id_doc_photo_b64.split(",")[1] if "," in id_doc_photo_b64 else id_doc_photo_b64
                decoded = base64.b64decode(b64_data)
                user.id_document_photo.save(f"doc_{uuid.uuid4().hex[:8]}.jpg", ContentFile(decoded), save=False)
            except Exception as e:
                logger.warning("Failed to decode id_document_photo_base64: %s", e)

        if pin:
            user.set_pin(pin)
        user.save()

        # Ensure primary USD wallet is provisioned with 0 balance
        from apps.wallets.models import Wallet, WalletStatus
        Wallet.objects.get_or_create(
            user=user,
            is_primary=True,
            defaults={
                "currency": "USD",
                "current_balance": 0,
                "available_balance": 0,
                "hold_balance": 0,
                "status": WalletStatus.ACTIVE,
            }
        )
        # Also provision the secondary Khmer Riel (KHR) wallet starting at 0 balance
        Wallet.objects.get_or_create(
            user=user,
            currency="KHR",
            defaults={
                "is_primary": False,
                "current_balance": 0,
                "available_balance": 0,
                "hold_balance": 0,
                "status": WalletStatus.ACTIVE,
            }
        )

        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.LOGIN_SUCCESS,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"action": "registration", "status": user.status}
        )

        session_data = (
            cls.create_user_session(user=user, ip_address=ip_address, user_agent=user_agent)
            if user.status == UserStatus.ACTIVE
            else None
        )
        return user, session_data

    @classmethod
    def create_user_session(
        cls,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: str = "",
        device_identifier: Optional[str] = None,
        device_name: Optional[str] = None,
        device_type: str = DeviceType.OTHER
    ) -> Dict:
        """Issues JWT token pair and records UserDevice and UserSession."""
        # Update device tracking
        device = None
        if device_identifier:
            device, created = UserDevice.objects.get_or_create(
                user=user,
                device_identifier=device_identifier,
                defaults={
                    "device_name": device_name or "Mobile / Browser",
                    "device_type": device_type,
                    "ip_address": ip_address,
                    "last_login_at": timezone.now(),
                    "is_active": True,
                }
            )
            if not created:
                device.ip_address = ip_address
                device.last_login_at = timezone.now()
                device.save(update_fields=["ip_address", "last_login_at", "updated_at"])

        # Generate JWT pair
        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email

        raw_refresh = str(refresh)
        raw_access = str(refresh.access_token)

        refresh_lifetime = getattr(settings, "SIMPLE_JWT", {}).get("REFRESH_TOKEN_LIFETIME", timedelta(days=7))
        expires_at = timezone.now() + refresh_lifetime

        token_hash = UserSession.hash_token(raw_refresh)
        session = UserSession.objects.create(
            user=user,
            device=device,
            refresh_token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            is_revoked=False
        )

        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at"])

        return {
            "access_token": raw_access,
            "refresh_token": raw_refresh,
            "token_type": "Bearer",
            "expires_in": int(getattr(settings, "SIMPLE_JWT", {}).get("ACCESS_TOKEN_LIFETIME", timedelta(minutes=15)).total_seconds()),
            "session_id": str(session.id)
        }

    @classmethod
    def rotate_session_token(cls, raw_refresh_token: str, ip_address: Optional[str] = None, user_agent: str = "") -> Dict:
        """Rotates refresh token and maintains session security audit."""
        token_hash = UserSession.hash_token(raw_refresh_token)

        try:
            session = UserSession.objects.select_related("user", "device").get(
                refresh_token_hash=token_hash
            )
        except UserSession.DoesNotExist:
            raise ValidationError("Invalid refresh token.")

        if not session.is_valid:
            # Token reuse detection: possible compromise!
            SecurityEvent.objects.create(
                user=session.user,
                event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "Attempted reuse of revoked or expired refresh token."}
            )
            raise ValidationError("Token has been revoked or expired.")

        # Revoke previous session
        session.is_revoked = True
        session.save(update_fields=["is_revoked", "updated_at"])

        # Issue new token pair
        user = session.user
        if not user.can_transact():
            raise ValidationError("Account is not active.")

        new_session_data = cls.create_user_session(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            device_identifier=session.device.device_identifier if session.device else None,
            device_name=session.device.device_name if session.device else None
        )
        return new_session_data

    @classmethod
    def revoke_session(cls, user: User, raw_refresh_token: str) -> None:
        """Revokes session and token on logout."""
        token_hash = UserSession.hash_token(raw_refresh_token)
        UserSession.objects.filter(user=user, refresh_token_hash=token_hash).update(
            is_revoked=True,
            updated_at=timezone.now()
        )
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEventType.LOGOUT,
            details={"action": "user_logout"}
        )
