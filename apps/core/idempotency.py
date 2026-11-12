import hashlib
import json
from functools import wraps
from typing import Callable
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from apps.core.exceptions import BankingException, IdempotencyConflictException
from apps.core.models import IdempotencyKey
from apps.core.responses import error_response


def calculate_request_hash(data) -> str:
    """Computes SHA-256 hash of serializable request payload."""
    try:
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def idempotent_request(key_header: str = "HTTP_IDEMPOTENCY_KEY"):
    """
    Decorator for DRF API view methods to guarantee idempotent financial mutations.
    Extracts Idempotency-Key header, checks existing records, and caches successful results.
    """
    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            raw_key = request.META.get(key_header) or request.headers.get("Idempotency-Key")

            if not raw_key:
                return error_response(
                    message="Idempotency-Key header is required for this financial operation.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    errors={"idempotency_key": ["Missing required Idempotency-Key header."]}
                )

            key_str = str(raw_key).strip()
            user = request.user
            if not user.is_authenticated:
                return view_func(self, request, *args, **kwargs)

            request_path = request.path
            params_hash = calculate_request_hash(request.data)

            # Atomic idempotency lookup and reservation
            with transaction.atomic():
                idempotency_record, created = IdempotencyKey.objects.select_for_update().get_or_create(
                    user=user,
                    key=key_str,
                    defaults={
                        "request_path": request_path,
                        "request_params_hash": params_hash,
                        "status": IdempotencyKey.Status.PENDING,
                    }
                )

                if not created:
                    if idempotency_record.status == IdempotencyKey.Status.RESOLVED:
                        # Return previously executed response payload
                        return Response(
                            idempotency_record.response_body,
                            status=idempotency_record.response_code or status.HTTP_200_OK
                        )
                    elif idempotency_record.status == IdempotencyKey.Status.PENDING:
                        raise IdempotencyConflictException(
                            "A financial request with this Idempotency-Key is currently in progress."
                        )
                    else:
                        # Previously failed: allow retry by resetting to PENDING
                        idempotency_record.status = IdempotencyKey.Status.PENDING
                        idempotency_record.request_params_hash = params_hash
                        idempotency_record.save(update_fields=["status", "request_params_hash", "updated_at"])

            try:
                response = view_func(self, request, *args, **kwargs)

                # If successful or expected business error, record response
                if response.status_code < 500:
                    with transaction.atomic():
                        rec = IdempotencyKey.objects.select_for_update().get(id=idempotency_record.id)
                        rec.status = IdempotencyKey.Status.RESOLVED
                        rec.response_code = response.status_code
                        rec.response_body = response.data
                        rec.save(update_fields=["status", "response_code", "response_body", "updated_at"])
                else:
                    with transaction.atomic():
                        rec = IdempotencyKey.objects.select_for_update().get(id=idempotency_record.id)
                        rec.status = IdempotencyKey.Status.FAILED
                        rec.save(update_fields=["status", "updated_at"])

                return response

            except BankingException as exc:
                # Store business error response so client receives same error upon retry
                with transaction.atomic():
                    rec = IdempotencyKey.objects.select_for_update().get(id=idempotency_record.id)
                    rec.status = IdempotencyKey.Status.RESOLVED
                    rec.response_code = exc.status_code
                    rec.response_body = {
                        "success": False,
                        "message": exc.message,
                        "errors": exc.errors or {"detail": exc.message}
                    }
                    rec.save(update_fields=["status", "response_code", "response_body", "updated_at"])
                raise

            except Exception:
                with transaction.atomic():
                    rec = IdempotencyKey.objects.select_for_update().get(id=idempotency_record.id)
                    rec.status = IdempotencyKey.Status.FAILED
                    rec.save(update_fields=["status", "updated_at"])
                raise

        return wrapper
    return decorator
