import logging
from typing import Any, Dict, Optional
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.exceptions import BankingException

logger = logging.getLogger("banking.api")


def success_response(
    data: Any = None,
    message: str = "Operation completed successfully.",
    status_code: int = status.HTTP_200_OK,
    headers: Optional[Dict[str, str]] = None
) -> Response:
    """Standardized API success envelope."""
    payload = {
        "success": True,
        "message": message,
        "data": data if data is not None else {}
    }
    return Response(payload, status=status_code, headers=headers)


def error_response(
    message: str = "An error occurred.",
    errors: Optional[Any] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    headers: Optional[Dict[str, str]] = None
) -> Response:
    """Standardized API error envelope."""
    payload = {
        "success": False,
        "message": message,
        "errors": errors if errors is not None else {}
    }
    return Response(payload, status=status_code, headers=headers)


def custom_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """Centralized exception handler that wraps all exceptions in standard API envelope."""
    # 1. Custom Domain / Banking Exceptions
    if isinstance(exc, BankingException):
        logger.warning(
            "Banking business rule violation [%s]: %s (view: %s)",
            exc.code,
            exc.message,
            context.get("view").__class__.__name__ if context.get("view") else "Unknown"
        )
        return error_response(
            message=exc.message,
            errors=exc.errors or {"detail": exc.message},
            status_code=exc.status_code
        )

    # 2. Standard Django Exceptions
    if isinstance(exc, DjangoValidationError):
        return error_response(
            message="Validation error.",
            errors=exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if isinstance(exc, Http404):
        return error_response(
            message="Requested resource not found.",
            status_code=status.HTTP_404_NOT_FOUND
        )

    if isinstance(exc, PermissionDenied):
        return error_response(
            message="You do not have permission to perform this action.",
            status_code=status.HTTP_403_FORBIDDEN
        )

    # 3. DRF Built-in API Exceptions
    response = drf_exception_handler(exc, context)

    if response is not None:
        errors_data = response.data
        message = "An error occurred."

        if isinstance(errors_data, dict):
            if "detail" in errors_data:
                message = str(errors_data["detail"])
            elif errors_data:
                first_key = next(iter(errors_data))
                first_val = errors_data[first_key]
                if isinstance(first_val, list) and first_val:
                    message = f"{first_key}: {first_val[0]}"
                else:
                    message = f"Invalid input for {first_key}."
        elif isinstance(errors_data, list) and errors_data:
            message = str(errors_data[0])

        return error_response(
            message=message,
            errors=errors_data if isinstance(errors_data, dict) else {"detail": errors_data},
            status_code=response.status_code
        )

    # 4. Unhandled 500 Server Errors
    logger.exception("Unhandled server error: %s", exc, exc_info=exc)
    internal_message = "An unexpected server error occurred. Please contact support."
    if settings.DEBUG:
        internal_message = f"{exc.__class__.__name__}: {str(exc)}"

    return error_response(
        message=internal_message,
        errors={"detail": "Internal server error"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
