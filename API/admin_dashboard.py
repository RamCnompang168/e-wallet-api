from django.db.models import Sum
from django.template.response import TemplateResponse
from apps.transactions.models import Transaction
from apps.users.models import User
from apps.wallets.models import Wallet


def operations_dashboard(request):
    """Read-only operational overview for staff users."""
    completed = Transaction.objects.filter(status=Transaction.Status.COMPLETED)
    context = {
        "title": "Operations dashboard",
        "active_users": User.objects.filter(is_active=True).count(),
        "active_wallets": Wallet.objects.filter(status=Wallet.Status.ACTIVE).count(),
        "frozen_wallets": Wallet.objects.filter(status=Wallet.Status.FROZEN).count(),
        "wallet_liability": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
        "completed_volume": completed.aggregate(total=Sum("amount"))["total"] or 0,
        "recent_transactions": completed.select_related("sender_wallet", "receiver_wallet")[:10],
    }
    return TemplateResponse(request, "admin/operations_dashboard.html", context)
