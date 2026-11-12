import secrets
from django.db import models
from apps.core.models import BaseModel
from apps.transactions.models import Transaction


def generate_batch_code() -> str:
    return f"REC-{secrets.token_hex(6).upper()}"


class WebhookStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    PROCESSING = "PROCESSING", "Processing"
    PROCESSED = "PROCESSED", "Processed Successfully"
    FAILED = "FAILED", "Failed Processing"
    DUPLICATE = "DUPLICATE", "Duplicate Event Skipped"


class WebhookEvent(BaseModel):
    """Inbound provider webhooks with HMAC signatures and replay attack protection."""
    provider = models.CharField(max_length=50, db_index=True)
    external_event_id = models.CharField(max_length=150, db_index=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    signature = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=30, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED, db_index=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Webhook Event"
        verbose_name_plural = "Webhook Events"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_event_id"],
                name="unique_provider_webhook_event"
            )
        ]
        indexes = [
            models.Index(fields=["provider", "status"]),
        ]

    def __str__(self):
        return f"[{self.provider}] Event: {self.external_event_id} ({self.status})"


class ReconciliationStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed (Clean Match)"
    DISCREPANCIES_FOUND = "DISCREPANCIES_FOUND", "Discrepancies Found"


class ReconciliationBatch(BaseModel):
    """Batch run comparing internal transactions against external provider statements."""
    batch_code = models.CharField(max_length=64, unique=True, default=generate_batch_code, editable=False)
    provider = models.CharField(max_length=50)
    reconciliation_date = models.DateField()
    total_internal_records = models.PositiveIntegerField(default=0)
    total_external_records = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    mismatch_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, choices=ReconciliationStatus.choices, default=ReconciliationStatus.IN_PROGRESS)

    class Meta:
        verbose_name = "Reconciliation Batch"
        verbose_name_plural = "Reconciliation Batches"

    def __str__(self):
        return f"Batch {self.batch_code} [{self.provider}] on {self.reconciliation_date} ({self.status})"


class RecordStatus(models.TextChoices):
    MATCHED = "MATCHED", "Matched Exactly"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH", "Amount Discrepancy"
    MISSING_INTERNAL = "MISSING_INTERNAL", "Present in External, Missing Internally"
    MISSING_EXTERNAL = "MISSING_EXTERNAL", "Present Internally, Missing Externally"


class ReconciliationRecord(BaseModel):
    """Detailed audit comparison for a single transaction during reconciliation."""
    batch = models.ForeignKey(
        ReconciliationBatch,
        on_delete=models.CASCADE,
        related_name="records"
    )
    internal_transaction = models.ForeignKey(
        Transaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reconciliation_records"
    )
    external_reference = models.CharField(max_length=150, db_index=True)
    internal_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    external_amount = models.DecimalField(max_digits=18, decimal_places=4)
    status = models.CharField(max_length=30, choices=RecordStatus.choices)
    discrepancy_details = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Reconciliation Record"
        verbose_name_plural = "Reconciliation Records"

    def __str__(self):
        return f"{self.external_reference}: {self.status}"
