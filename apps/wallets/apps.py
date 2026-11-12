from django.apps import AppConfig


class WalletsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wallets"
    label = "wallets"

    def ready(self):
        from . import signals  # noqa: F401
