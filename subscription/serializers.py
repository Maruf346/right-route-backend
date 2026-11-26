from decimal import Decimal
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from core.constants import (
    BillingType,
    CouponDiscountType,
    CouponDurationType,
    CouponPlanScope,
    PURCHASE_PLATFORM,
    PlanType,
    UserSubscriptionStatus,
)

from .models import (
    CouponRedemption,
    DiscountCoupon,
    FleetAccount,
    SubscriptionPlan,
    UserSubscription,
)


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ("id", "name", "product_id", "plan_type", "billing_type", "team_limit", "price", "currency", "trial_days", "features_json", "is_active", "created_at", "updated_at", )
        read_only_fields = ("id", "created_at", "updated_at")


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField( source="plan.name", read_only=True)
    plan_type = serializers.CharField( source="plan.plan_type", read_only=True)
    billing_type = serializers.CharField( source="plan.billing_type", read_only=True)
    plan_product_id = serializers.CharField(source="plan.product_id", read_only=True)
    plan_price = serializers.DecimalField( source="plan.price", max_digits=10, decimal_places=2, read_only=True)
    team_limit = serializers.IntegerField(source="plan.team_limit",read_only=True)
    trial_days = serializers.IntegerField(source="plan.trial_days", read_only=True)
    
    # Team Details
    team_name = serializers.CharField(source="team.name",read_only=True)
    team_id = serializers.IntegerField(source="team.id",read_only=True)

    # User Details
    user_id = serializers.IntegerField(source="user.id",read_only=True)
    user_email = serializers.EmailField(source="user.email",read_only=True)

    # Computed Property
    is_valid = serializers.BooleanField(read_only=True)
    purchase_verification_status = serializers.SerializerMethodField()
    latest_purchase_transaction_id = serializers.SerializerMethodField()

    class Meta:
        model = UserSubscription
        exclude = ("user", "team", "plan")



    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_purchase_verification_status(self, obj):
        purchase_info = obj.purchase_info.order_by("-created_at").first()
        return purchase_info.verification_status if purchase_info else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_purchase_transaction_id(self, obj):
        purchase_info = obj.purchase_info.order_by("-created_at").first()
        return purchase_info.transaction_id if purchase_info else obj.latest_transaction_id

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
            "discount_period",
            "discount_amount",
            "state",
            "notes",
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
    notes = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True, max_length=100)
    discount_period = serializers.CharField(required=False, allow_blank=True, max_length=100)
    discount_amount = serializers.CharField(required=False, allow_blank=True, max_length=100)

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

        sub_dirty = False
        for field in ("status", "notes", "state", "discount_period", "discount_amount"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
                sub_dirty = True
        if sub_dirty:
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
    subscription_plan_uuid = serializers.UUIDField(required=True)
    product_id = serializers.CharField(required=True, max_length=100)
    transaction_id = serializers.CharField(required=True, max_length=255)
    original_transaction_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    purchase_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    receipt_data = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    package_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    order_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    amount = serializers.DecimalField(required=False, allow_null=True, max_digits=10, decimal_places=2)
    currency = serializers.CharField(required=False, allow_blank=True, max_length=10, default="USD")
    purchase_time = serializers.DateTimeField(required=False, allow_null=True)
    expiry_time = serializers.DateTimeField(required=False, allow_null=True)
    auto_renew = serializers.BooleanField(required=False, default=False)
    raw_response = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        platform = attrs["platform"]
        if platform == PURCHASE_PLATFORM.ANDROID and not attrs.get("purchase_token"):
            raise serializers.ValidationError({"purchase_token": "Required for Android purchases."})
        if platform == PURCHASE_PLATFORM.IOS and not (attrs.get("receipt_data") or attrs.get("transaction_id")):
            raise serializers.ValidationError({"receipt_data": "Required for iOS purchases when transaction_id is not enough."})
        return attrs



class PurchaseSubscriptionResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = UserSubscriptionSerializer()


class VerifyPurchaseResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    subscription_status = serializers.CharField()
    purchase_id = serializers.IntegerField()
    transaction_id = serializers.CharField()
    verification_status = serializers.CharField()
    data = UserSubscriptionSerializer()


class RestorePurchaseItemSerializer(serializers.Serializer):
    product_id = serializers.CharField(required=True, max_length=100)
    transaction_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    original_transaction_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    purchase_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    receipt_data = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    package_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    order_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    purchase_time = serializers.DateTimeField(required=False, allow_null=True)
    expiry_time = serializers.DateTimeField(required=False, allow_null=True)
    auto_renew = serializers.BooleanField(required=False, default=True)
    raw_response = serializers.JSONField(required=False, default=dict)


class RestorePurchasesSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=PURCHASE_PLATFORM.choices, default=PURCHASE_PLATFORM.ANDROID)
    purchases = RestorePurchaseItemSerializer(many=True, required=False, default=list)


class RestorePurchasesResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    restored = serializers.BooleanField()
    message = serializers.CharField()
    data = UserSubscriptionSerializer(allow_null=True)


class GooglePlayRTDNSerializer(serializers.Serializer):
    message = serializers.DictField(required=False)
    subscription = serializers.CharField(required=False, allow_blank=True)


class FleetAccountSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    active_drivers = serializers.SerializerMethodField()
    last_time_active = serializers.DateTimeField(source="user.last_login", read_only=True)
    locked = serializers.SerializerMethodField()

    class Meta:
        model = FleetAccount
        fields = [
            "id",
            "uuid",
            "user_id",
            "team_id",
            "team_name",
            "full_name",
            "company_name",
            "email",
            "phone",
            "sign_up_date",
            "next_payment_date",
            "last_time_active",
            "status",
            "driver_allowance",
            "active_drivers",
            "price",
            "billing_type",
            "discount_period",
            "discount_amount",
            "state",
            "platform",
            "notes",
            "locked",
            "stripe_customer_id",
            "stripe_subscription_id",
            "stripe_latest_invoice_id",
            "stripe_invoice_url",
            "stripe_sync_status",
            "stripe_sync_error",
            "welcome_email_sent_at",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField)
    def get_active_drivers(self, obj):
        if not obj.team_id:
            return 0
        return obj.team.members.filter(status=True).count()

    @extend_schema_field(serializers.BooleanField)
    def get_locked(self, obj):
        return not obj.user.is_active


class FleetAccountWriteSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    sign_up_date = serializers.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"],
    )
    next_payment_date = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"],
    )
    driver_allowance = serializers.IntegerField(min_value=1, required=False, default=100)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0.00"))
    billing_type = serializers.ChoiceField(choices=BillingType.choices, required=False, default=BillingType.MONTHLY)
    discount_period = serializers.CharField(max_length=100, required=False, allow_blank=True, default="0")
    discount_amount = serializers.CharField(max_length=100, required=False, allow_blank=True, default="0")
    state = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    platform = serializers.CharField(max_length=50, required=False, allow_blank=True, default="Stripe")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=UserSubscriptionStatus.choices,
        required=False,
        default=UserSubscriptionStatus.ACTIVE,
    )

    def validate_email(self, value):
        value = value.strip().lower()
        from account.models import User
        qs = User.objects.filter(email=value)
        if self.instance is not None:
            qs = qs.exclude(id=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class FleetWelcomeEmailSerializer(serializers.Serializer):
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)


class DiscountCouponSerializer(serializers.ModelSerializer):
    discount_period_label = serializers.CharField(source="get_discount_period_label", read_only=True)
    discount_amount_label = serializers.CharField(source="get_discount_amount_label", read_only=True)
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True, allow_null=True)

    class Meta:
        model = DiscountCoupon
        fields = [
            "id",
            "code",
            "description",
            "discount_type",
            "discount_value",
            "duration",
            "duration_in_months",
            "applicable_plan_type",
            "max_redemptions",
            "times_redeemed",
            "valid_from",
            "valid_until",
            "is_active",
            "stripe_coupon_id",
            "stripe_promotion_code_id",
            "discount_period_label",
            "discount_amount_label",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "times_redeemed",
            "stripe_coupon_id",
            "stripe_promotion_code_id",
            "discount_period_label",
            "discount_amount_label",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", CouponDiscountType.PERCENTAGE))
        discount_value = attrs.get("discount_value", getattr(self.instance, "discount_value", Decimal("0")))
        duration = attrs.get("duration", getattr(self.instance, "duration", CouponDurationType.ONCE))
        months = attrs.get("duration_in_months", getattr(self.instance, "duration_in_months", None))

        if discount_value <= 0:
            raise serializers.ValidationError({"discount_value": "Discount value must be greater than zero."})
        if discount_type == CouponDiscountType.PERCENTAGE and discount_value > Decimal("100"):
            raise serializers.ValidationError({"discount_value": "Percentage discount cannot exceed 100%."})
        if duration == CouponDurationType.REPEATING and (not months or months < 1):
            raise serializers.ValidationError(
                {"duration_in_months": "Provide duration in months for repeating coupons."}
            )
        return attrs


class CouponRedemptionSerializer(serializers.ModelSerializer):
    coupon_code = serializers.CharField(source="coupon.code", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True, allow_null=True)

    class Meta:
        model = CouponRedemption
        fields = [
            "id",
            "coupon",
            "coupon_code",
            "user",
            "user_email",
            "plan",
            "plan_name",
            "original_price",
            "discount_amount",
            "final_price",
            "stripe_checkout_session_id",
            "status",
            "created_at",
        ]


class CouponValidateSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=64)
    plan_id = serializers.IntegerField(required=True)


class WebCheckoutCreateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(required=True)
    coupon_code = serializers.CharField(required=False, allow_blank=True, max_length=64)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    success_url = serializers.URLField(required=False, allow_blank=True)
    cancel_url = serializers.URLField(required=False, allow_blank=True)


class WebCheckoutConfirmTestSerializer(serializers.Serializer):
    session_id = serializers.CharField(required=True, max_length=255)
