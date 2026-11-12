import django_filters
from apps.transactions.models import Transaction, TransactionStatus, TransactionType


class TransactionFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=TransactionStatus.choices)
    transaction_type = django_filters.ChoiceFilter(choices=TransactionType.choices)
    date_from = django_filters.DateFilter(field_name="created_at__date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="created_at__date", lookup_expr="lte")
    min_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="lte")
    reference_number = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Transaction
        fields = [
            "status",
            "transaction_type",
            "currency",
            "date_from",
            "date_to",
            "min_amount",
            "max_amount",
            "reference_number",
        ]
