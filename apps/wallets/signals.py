from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.users.models import User, UserRole
from apps.wallets.models import Wallet


@receiver(post_save, sender=User)
def create_user_default_wallet(sender, instance, created, **kwargs):
    """Automatically provisions a default active wallet when a customer or merchant registers."""
    if created and instance.role in [UserRole.CUSTOMER, UserRole.MERCHANT]:
        Wallet.objects.get_or_create(
            user=instance,
            is_primary=True,
            defaults={
                "currency": "USD",
                "current_balance": Decimal("0.0000"),
                "available_balance": Decimal("0.0000"),
                "hold_balance": Decimal("0.0000"),
            }
        )
