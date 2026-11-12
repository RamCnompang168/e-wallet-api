from django.conf import settings
from django.db import models
from apps.core.models import BaseModel


class NotificationType(models.TextChoices):
    TRANSACTION = "TRANSACTION", "Transaction Alert"
    SECURITY = "SECURITY", "Security Event"
    KYC = "KYC", "Identity Verification"
    DISPUTE = "DISPUTE", "Dispute Update"
    SYSTEM = "SYSTEM", "System Notice"


class Notification(BaseModel):
    """User alert notifications for transactions, security, and account status."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="notifications",
        on_delete=models.CASCADE
    )
    related_transaction = models.ForeignKey(
        "transactions.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications"
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.TRANSACTION,
        db_index=True
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.title} for {self.user.email} (Read: {self.is_read})"
