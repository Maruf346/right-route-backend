from rest_framework import serializers

from .models import SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("id", "name", "plan_type", "billing_type", "team_limit", "price", "features_json", "is_active", "created_at", "updated_at", )
        read_only_fields = ("id", "created_at", "updated_at")


