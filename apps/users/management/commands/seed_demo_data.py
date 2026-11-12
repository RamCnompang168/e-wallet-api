from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.transactions.services.transfer_service import simulate_balance_change, transfer_money
from apps.users.models import User
from apps.users.security import set_pin


class Command(BaseCommand):
    help = "Create two repeatable demo e-wallet accounts and sample transactions."

    def handle(self, *args, **options):
        sokha, created = User.objects.get_or_create(phone_number="+85512000010", defaults={"email": "sokha@example.com", "full_name": "Sokha Chan"})
        if created:
            sokha.set_password("DemoPass123!")
            sokha.save(update_fields=["password"])
            set_pin(sokha, "123456")
        thida, created = User.objects.get_or_create(phone_number="+85512000020", defaults={"email": "thida@example.com", "full_name": "Thida Meas"})
        if created:
            thida.set_password("DemoPass123!")
            thida.save(update_fields=["password"])
            set_pin(thida, "654321")
        if sokha.wallet.balance == 0:
            simulate_balance_change(wallet_id=sokha.wallet.id, amount=Decimal("1000.0000"), deposit=True)
            transfer_money(sender_wallet_id=sokha.wallet.id, receiver_wallet_number=thida.wallet.wallet_number, amount=Decimal("75.2500"), notes="Demo transfer", idempotency_key="demo-transfer-001")
        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Sokha: {sokha.wallet.wallet_number}; Thida: {thida.wallet.wallet_number}"))
