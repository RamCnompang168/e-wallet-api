import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base model adding created_at and updated_at timestamps."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class UUIDModel(models.Model):
    """Abstract base model with UUID primary key."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """Combines UUID primary key and timestamp audit fields."""
    class Meta:
        abstract = True


def default_idempotency_expiry():
    return timezone.now() + timedelta(hours=24)


class IdempotencyKey(BaseModel):
    """Stores API request idempotency keys and cached response payloads."""
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RESOLVED = "RESOLVED", "Resolved"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_keys"
    )
    key = models.CharField(max_length=255, db_index=True)
    request_path = models.CharField(max_length=255)
    request_params_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    expires_at = models.DateTimeField(default=default_idempotency_expiry)

    class Meta:
        verbose_name = "Idempotency Key"
        verbose_name_plural = "Idempotency Keys"
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="unique_user_idempotency_key")
        ]
        indexes = [
            models.Index(fields=["user", "key"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.key} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at
