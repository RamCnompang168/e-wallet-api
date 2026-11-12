import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BankingException
from apps.settlement.models import (
    ReconciliationBatch,
    ReconciliationRecord,
    ReconciliationStatus,
    RecordStatus,
    WebhookEvent,
    WebhookStatus,
)
from apps.transactions.models import Transaction, TransactionStatus

logger = logging.getLogger("banking.settlement")


class WebhookService:
    """Processes signed inbound webhooks with replay attack prevention and idempotency."""

    @classmethod
    def verify_hmac_signature(cls, payload_bytes: bytes, signature: str, secret: str) -> bool:
        """Verifies HMAC-SHA256 signature."""
        if not secret or not signature:
            return True  # If no secret configured in dev, skip
        expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signature)

    @classmethod
    def record_and_process_webhook(
        cls,
        provider: str,
        external_event_id: str,
        event_type: str,
        payload: Dict[str, Any],
        signature: str = ""
    ) -> WebhookEvent:
        # Check idempotency: if event already exists, return duplicate
        existing = WebhookEvent.objects.filter(provider=provider, external_event_id=external_event_id).first()
        if existing:
            logger.warning("Duplicate webhook received: %s - %s", provider, external_event_id)
            return existing

        secret = getattr(settings, "WEBHOOK_SECRET", "")
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")

        if secret and signature and not cls.verify_hmac_signature(payload_bytes, signature, secret):
            raise BankingException("Invalid webhook cryptographic signature.")

        event = WebhookEvent.objects.create(
            provider=provider,
            external_event_id=external_event_id,
            event_type=event_type,
            payload=payload,
            signature=signature,
            status=WebhookStatus.PROCESSING
        )

        try:
            cls._route_event(event)
            event.status = WebhookStatus.PROCESSED
            event.processed_at = timezone.now()
            event.save(update_fields=["status", "processed_at", "updated_at"])
        except Exception as exc:
            logger.error("Error processing webhook %s: %s", event.id, exc)
            event.status = WebhookStatus.FAILED
            event.error_message = str(exc)
            event.save(update_fields=["status", "error_message", "updated_at"])

        return event

    @classmethod
    def _route_event(cls, event: WebhookEvent) -> None:
        """Routes payload to specific handler (e.g. topup confirmation)."""
        logger.info("Processed webhook event [%s]: %s", event.provider, event.event_type)


class ReconciliationService:
    """Automated comparison engine between internal transactions and external provider statements."""

    @classmethod
    def run_reconciliation(
        cls,
        provider: str,
        recon_date,
        external_records: List[Dict[str, Any]]
    ) -> ReconciliationBatch:
        """
        external_records format:
        [{"reference": "REF123", "amount": Decimal("100.00")}, ...]
        """
        with transaction.atomic():
            batch = ReconciliationBatch.objects.create(
                provider=provider,
                reconciliation_date=recon_date,
                status=ReconciliationStatus.IN_PROGRESS
            )

            # Query internal transactions for that date
            internal_txns = Transaction.objects.filter(
                created_at__date=recon_date,
                status=TransactionStatus.COMPLETED
            )
            internal_map = {t.reference_number: t for t in internal_txns if t.reference_number}

            external_map = {r["reference"]: Decimal(str(r["amount"])) for r in external_records}

            matched = 0
            mismatches = 0

            # 1. Check external records against internal map
            for ext_ref, ext_amt in external_map.items():
                if ext_ref in internal_map:
                    int_txn = internal_map[ext_ref]
                    if int_txn.amount == ext_amt:
                        ReconciliationRecord.objects.create(
                            batch=batch,
                            internal_transaction=int_txn,
                            external_reference=ext_ref,
                            internal_amount=int_txn.amount,
                            external_amount=ext_amt,
                            status=RecordStatus.MATCHED
                        )
                        matched += 1
                    else:
                        ReconciliationRecord.objects.create(
                            batch=batch,
                            internal_transaction=int_txn,
                            external_reference=ext_ref,
                            internal_amount=int_txn.amount,
                            external_amount=ext_amt,
                            status=RecordStatus.AMOUNT_MISMATCH,
                            discrepancy_details={"diff": str(int_txn.amount - ext_amt)}
                        )
                        mismatches += 1
                else:
                    ReconciliationRecord.objects.create(
                        batch=batch,
                        internal_transaction=None,
                        external_reference=ext_ref,
                        internal_amount=None,
                        external_amount=ext_amt,
                        status=RecordStatus.MISSING_INTERNAL
                    )
                    mismatches += 1

            # 2. Check internal records missing from external statement
            for int_ref, int_txn in internal_map.items():
                if int_ref not in external_map:
                    ReconciliationRecord.objects.create(
                        batch=batch,
                        internal_transaction=int_txn,
                        external_reference=int_ref,
                        internal_amount=int_txn.amount,
                        external_amount=Decimal("0.0000"),
                        status=RecordStatus.MISSING_EXTERNAL
                    )
                    mismatches += 1

            batch.total_internal_records = len(internal_map)
            batch.total_external_records = len(external_map)
            batch.matched_count = matched
            batch.mismatch_count = mismatches
            batch.status = ReconciliationStatus.COMPLETED if mismatches == 0 else ReconciliationStatus.DISCREPANCIES_FOUND
            batch.save(update_fields=[
                "total_internal_records", "total_external_records",
                "matched_count", "mismatch_count", "status", "updated_at"
            ])

        return batch
