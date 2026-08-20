from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from core.constants import PURCHASE_PLATFORM, PlanType, UserSubscriptionStatus

from .models import SubscriptionPlan, UserSubscription


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("id", "name", "plan_type", "billing_type", "team_limit", "price", "currency", "features_json", "is_active", "created_at", "updated_at", )
        read_only_fields = ("id", "created_at", "updated_at")


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

    # Computed Property
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserSubscription
        exclude = ("user", "team", "plan")


class AdminSubscriberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    sign_up_date = serializers.DateTimeField(source="starts_at", read_only=True)
    next_payment = serializers.DateTimeField(source="expires_at", read_only=True)
    last_time_active = serializers.DateTimeField(source="user.last_login", read_only=True)
    account_status = serializers.CharField(source="status", read_only=True)
    current_plan = serializers.CharField(source="plan.name", read_only=True)
    plan_id = serializers.IntegerField(source="plan.id", read_only=True)
    plan_type = serializers.CharField(source="plan.plan_type", read_only=True)
    billing_type = serializers.CharField(source="plan.billing_type", read_only=True)
    price = serializers.DecimalField(source="plan.price", max_digits=10, decimal_places=2, read_only=True)
    platform = serializers.SerializerMethodField()
    locked = serializers.SerializerMethodField()

    class Meta:
        model = UserSubscription
        fields = [
            "id",
            "uuid",
            "user_id",
            "email",
            "sign_up_date",
            "next_payment",
            "last_time_active",
            "account_status",
            "current_plan",
            "plan_id",
            "plan_type",
            "billing_type",
            "price",
            "platform",
            "locked",
            "auto_renew",
            "payment_status",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_platform(self, obj):
        purchase_info = obj.purchase_info.order_by("-created_at").first()
        if purchase_info:
            return purchase_info.platform

        purchase_info = obj.user.purchase_info.order_by("-created_at").first()
        return purchase_info.platform if purchase_info else None

    @extend_schema_field(serializers.BooleanField)
    def get_locked(self, obj):
        return not obj.user.is_active


class AdminTeamSubscriberSerializer(AdminSubscriberSerializer):
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    active_drivers = serializers.SerializerMethodField()
    driver_limit = serializers.IntegerField(source="plan.team_limit", read_only=True)

    class Meta(AdminSubscriberSerializer.Meta):
        fields = AdminSubscriberSerializer.Meta.fields + [
            "team_id",
            "team_name",
            "active_drivers",
            "driver_limit",
        ]

    @extend_schema_field(serializers.IntegerField)
    def get_active_drivers(self, obj):
        if not obj.team:
            return 0
        return obj.team.members.filter(status=True).count()


class AdminSubscriberUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    password = serializers.CharField(write_only=True, required=False)
    status = serializers.ChoiceField(choices=UserSubscriptionStatus.choices, required=False)

    def validate_email(self, value):
        value = value.lower()
        if self.instance.user.__class__.objects.exclude(id=self.instance.user_id).filter(email=value).exists():
            raise serializers.ValidationError("User with this email already exists.")
        return value

    def update(self, instance, validated_data):
        if "email" in validated_data:
            instance.user.email = validated_data["email"]
        if "password" in validated_data:
            instance.user.set_password(validated_data["password"])
        if "email" in validated_data or "password" in validated_data:
            instance.user.save()

        if "status" in validated_data:
            instance.status = validated_data["status"]
        if "status" in validated_data:
            instance.save()
        return instance


class AdminSingleSubscriberUpdateSerializer(AdminSubscriberUpdateSerializer):
    plan_type = PlanType.INDIVIDUAL


class AdminTeamSubscriberUpdateSerializer(AdminSubscriberUpdateSerializer):
    plan_type = PlanType.TEAM


class AdminSubscriberListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    count = serializers.IntegerField()
    data = AdminSubscriberSerializer(many=True)


class AdminTeamSubscriberListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    count = serializers.IntegerField()
    data = AdminTeamSubscriberSerializer(many=True)


class AdminSubscriberRetrieveResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = AdminSubscriberSerializer()


class AdminTeamSubscriberRetrieveResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = AdminTeamSubscriberSerializer()


class AdminSubscriberUpdateResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminSubscriberSerializer()


class AdminTeamSubscriberUpdateResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminTeamSubscriberSerializer()


class AdminSubscriberAccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminSubscriberSerializer()


class AdminTeamSubscriberAccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminTeamSubscriberSerializer()


class AdminSubscriberDeleteResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()

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

class VerifyPurchaseSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=PURCHASE_PLATFORM.choices)
    subscription_plan_uuid = serializers.CharField(required=True)
    transaction_id = serializers.CharField(required=False)
    product_id = serializers.CharField(required=False)
    purchase_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    receipt_data = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    package_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # def validate(self, attrs):
    #     platform = attrs["platform"]
    #     if platform == PURCHASE_PLATFORM.ANDROID:
    #         if not attrs.get("purchase_token"):
    #             raise serializers.ValidationError({
    #                 "purchase_token": "Required for Android."
    #             })
    #     elif platform == PURCHASE_PLATFORM.IOS:
    #         if not attrs.get("receipt_data"):
    #             raise serializers.ValidationError({
    #                 "receipt_data": "Required for iOS."
    #             })
    #     return attrs


