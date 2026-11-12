from rest_framework import serializers


class AnalyticsSerializer(serializers.Serializer):
    income = serializers.ListField(child=serializers.DictField())
    expense = serializers.ListField(child=serializers.DictField())
