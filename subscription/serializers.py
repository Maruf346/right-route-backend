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

class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField( source="plan.name", read_only=True)
    plan_type = serializers.CharField( source="plan.plan_type", read_only=True)
    billing_type = serializers.CharField( source="plan.billing_type", read_only=True)
    plan_price = serializers.DecimalField( source="plan.price", max_digits=10, decimal_places=2, read_only=True)
    team_limit = serializers.IntegerField(source="plan.team_limit",read_only=True)
    
    # Team Details
    team_name = serializers.CharField(source="team.name",read_only=True)
    team_id = serializers.IntegerField(source="team.id",read_only=True)

    # User Details
    user_id = serializers.IntegerField(source="user.id",read_only=True)
    user_email = serializers.EmailField(source="user.email",read_only=True)
    user_username = serializers.CharField(source="user.username",read_only=True)

    # Computed Property
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserSubscription
        exclude = ("user", "team", "plan")
        # fields = "__all__"
        # read_only_fields = (
        #     "id",
        #     "created_at",
        #     "updated_at",
        # )

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



