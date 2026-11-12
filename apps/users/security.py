from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import User


def set_pin(user, pin):
    user.pin_hash = make_password(pin)
    user.pin_retry_count = 0
    user.is_locked = False
    user.save(update_fields=["pin_hash", "pin_retry_count", "is_locked", "updated_at"])


def verify_pin(user, pin):
    """Verify PIN while serializing retry count updates for concurrent requests."""
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        if locked_user.is_locked:
            locked = True
            invalid = False
        elif not locked_user.pin_hash or not check_password(pin, locked_user.pin_hash):
            locked = False
            invalid = True
            locked_user.pin_retry_count += 1
            if locked_user.pin_retry_count >= 3:
                locked_user.is_locked = True
            locked_user.save(update_fields=["pin_retry_count", "is_locked", "updated_at"])
        else:
            locked = False
            invalid = False
        if not locked and not invalid and locked_user.pin_retry_count:
            locked_user.pin_retry_count = 0
            locked_user.save(update_fields=["pin_retry_count", "updated_at"])
    if locked:
        raise PermissionDenied("Account is locked. Contact support.")
    if invalid:
        raise ValidationError("Invalid transaction PIN.")
    return locked_user
