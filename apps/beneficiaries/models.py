from django.conf import settings
from django.db import models
from apps.core.models import BaseModel
from apps.wallets.models import Wallet


class Beneficiary(BaseModel):
    """Saved transfer contacts associated with an existing active wallet."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="beneficiaries",
        on_delete=models.CASCADE
    )
    beneficiary_wallet = models.ForeignKey(
        Wallet,
        related_name="saved_by_users",
        on_delete=models.PROTECT
    )
    nickname = models.CharField(max_length=100)
    is_favorite = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Beneficiary"
        verbose_name_plural = "Beneficiaries"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "beneficiary_wallet"],
                name="unique_user_beneficiary_wallet"
            )
        ]
        ordering = ["-is_favorite", "nickname"]

    def __str__(self):
        return f"{self.nickname} ({self.beneficiary_wallet.wallet_number}) for {self.user.email}"
