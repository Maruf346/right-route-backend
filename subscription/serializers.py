from rest_framework import serializers

from .models import SubscriptionPlan, UserSubscription


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("id", "name", "plan_type", "billing_type", "team_limit", "price", "features_json", "is_active", "created_at", "updated_at", )
        read_only_fields = ("id", "created_at", "updated_at")


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name",read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)

    class Meta:
        model = UserSubscription
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

class PurchaseSubscriptionSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()

    def validate_plan_id(self, value):
        try:
            plan = SubscriptionPlan.objects.get(
                id=value,
                is_active=True
            )
        except SubscriptionPlan.DoesNotExist:
            raise serializers.ValidationError(
                "Subscription plan not found."
            )
        self.context["plan"] = plan
        return value



