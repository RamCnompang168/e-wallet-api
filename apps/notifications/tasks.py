import logging
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger("banking.celery")


@shared_task
def send_notification_email_task(recipient_email: str, subject: str, message: str) -> bool:
    """Asynchronous worker task to dispatch email alerts."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "NovaPay Alerts <no-reply@novapay.bank>"),
            recipient_list=[recipient_email],
            fail_silently=True
        )
        logger.info("Sent email to %s: %s", recipient_email, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient_email, exc)
        return False


@shared_task
def purge_expired_otps_task() -> int:
    """Scheduled task to clean up old expired OTP codes."""
    from apps.authentication.models import OTPCode
    count, _ = OTPCode.objects.filter(expires_at__lt=timezone.now()).delete()
    logger.info("Purged %d expired OTP codes.", count)
    return count
