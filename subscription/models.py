from decimal import Decimal
from django.conf import settings
from django.db import models
from core.common_models import BaseModel
from core.constants import (
    BillingType,
    CouponDiscountType,
    CouponDurationType,
    CouponPlanScope,
    PlanType,
    UserSubscriptionStatus,
    PaymentStatus,
    PaymentTransactionStatus,
    PURCHASE_VERIFY_STATUS,
    PURCHASE_PLATFORM,
)
from account.models import UserPaymentMethod, User, Team
from django.utils import timezone
import uuid

class SubscriptionPlan(BaseModel):
    name = models.CharField(max_length=255)
    product_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)
    billing_type = models.CharField(max_length=20, choices=BillingType.choices)
    team_limit = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    trial_days = models.PositiveIntegerField(default=7)
    features_json = models.JSONField(default=dict, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = [
            "team_limit",
            "billing_type",
            "plan_type",
        ]
    
    def __str__(self):
        return self.name

class UserSubscription(BaseModel):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, related_name="subscriptions", blank=True, null=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")

    status = models.CharField(max_length=30, choices=UserSubscriptionStatus.choices, default=UserSubscriptionStatus.PENDING)
    starts_at = models.DateTimeField()
    last_renew_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    
    auto_renew = models.BooleanField(default=False)
    renewal_attempt_count = models.PositiveIntegerField(default=0)
    grace_period_until = models.DateTimeField(blank=True, null=True)

    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    original_transaction_id = models.CharField(max_length=255, blank=True, null=True)
    latest_transaction_id = models.CharField(max_length=255, unique=True, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    discount_period = models.CharField(max_length=100, blank=True, default="0")
    discount_amount = models.CharField(max_length=100, blank=True, default="0")
    state = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    welcome_email_sent_at = models.DateTimeField(null=True, blank=True)
        
    @property
    def is_valid(self):
        now = timezone.now()
        if (
            self.status in [
                UserSubscriptionStatus.ACTIVE,
                UserSubscriptionStatus.TRIAL,
            ]
            and self.expires_at
            and self.expires_at > now
        ):
            return True

        if (
            self.status == UserSubscriptionStatus.GRACE_PERIOD
            and self.grace_period_until
            and self.grace_period_until > now
        ):
            return True
        return False

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["status"]),
        ]

class PurchaseInfo(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="purchase_info")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_info")
    platform = models.CharField(max_length=20, choices=PURCHASE_PLATFORM.choices)
    product_id = models.CharField(max_length=100, blank=True, null=True)
    transaction_id = models.CharField(max_length=255, unique=True)
    original_transaction_id = models.CharField(max_length=255, blank=True, null=True)
    purchase_token = models.TextField(blank=True, null=True)
    receipt_data = models.TextField(blank=True, null=True)
    package_name = models.CharField(max_length=255, blank=True, null=True)
    order_id = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=10, default="USD")
    purchase_time = models.DateTimeField()
    expiry_time = models.DateTimeField(blank=True, null=True)
    auto_renew = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=20, choices=PURCHASE_VERIFY_STATUS.choices, default=PURCHASE_VERIFY_STATUS.PENDING)
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class FleetAccount(BaseModel):
    """Enterprise Fleet customer record managed from Admin Dashboard and synced with Stripe."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="fleet_account")
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name="fleet_account")
    subscription = models.ForeignKey(
        UserSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fleet_accounts",
    )

    full_name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")

    sign_up_date = models.DateField(default=timezone.localdate)
    next_payment_date = models.DateField(null=True, blank=True, db_index=True)
    driver_allowance = models.PositiveIntegerField(default=100)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    billing_type = models.CharField(max_length=20, choices=BillingType.choices, default=BillingType.MONTHLY)

    discount_period = models.CharField(max_length=100, blank=True, default="0")
    discount_amount = models.CharField(max_length=100, blank=True, default="0")
    state = models.CharField(max_length=100, blank=True, default="")
    platform = models.CharField(max_length=50, blank=True, default="Stripe")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=30,
        choices=UserSubscriptionStatus.choices,
        default=UserSubscriptionStatus.ACTIVE,
        db_index=True,
    )

    stripe_customer_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    stripe_latest_invoice_id = models.CharField(max_length=255, blank=True, default="")
    stripe_invoice_url = models.URLField(max_length=500, blank=True, default="")
    stripe_sync_status = models.CharField(max_length=40, default="PENDING")
    stripe_sync_error = models.TextField(blank=True, default="")
    welcome_email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company_name or self.full_name} ({self.user.email})"


class DiscountCoupon(BaseModel):
    """Web & Fleet promotional discount coupon managed in Admin Dashboard and synced to Stripe."""

    code = models.CharField(max_length=64, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, default="")
    discount_type = models.CharField(
        max_length=20,
        choices=CouponDiscountType.choices,
        default=CouponDiscountType.PERCENTAGE,
    )
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    duration = models.CharField(
        max_length=20,
        choices=CouponDurationType.choices,
        default=CouponDurationType.ONCE,
    )
    duration_in_months = models.PositiveIntegerField(null=True, blank=True)
    applicable_plan_type = models.CharField(
        max_length=20,
        choices=CouponPlanScope.choices,
        default=CouponPlanScope.ALL,
    )
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    times_redeemed = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    stripe_coupon_id = models.CharField(max_length=255, blank=True, default="")
    stripe_promotion_code_id = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_coupons",
    )

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def get_discount_period_label(self):
        if self.duration == CouponDurationType.FOREVER:
            return "Forever"
        if self.duration == CouponDurationType.REPEATING and self.duration_in_months:
            unit = "month" if self.duration_in_months == 1 else "months"
            return f"{self.duration_in_months} {unit}"
        return "1 billing cycle"

    def get_discount_amount_label(self):
        if self.discount_type == CouponDiscountType.PERCENTAGE:
            val = self.discount_value.normalize()
            return f"{val}% off"
        return f"${self.discount_value:,.2f} off"

    def compute_discount(self, base_price):
        base = Decimal(str(base_price or "0.00"))
        if self.discount_type == CouponDiscountType.PERCENTAGE:
            pct = min(max(self.discount_value, Decimal("0")), Decimal("100"))
            discount = (base * pct / Decimal("100")).quantize(Decimal("0.01"))
        else:
            discount = min(max(self.discount_value, Decimal("0")), base).quantize(Decimal("0.01"))
        final_price = max(base - discount, Decimal("0.00")).quantize(Decimal("0.01"))
        return discount, final_price

    def validate_for_plan_type(self, target_plan_type=None, now=None):
        now = now or timezone.now()
        if not self.is_active:
            return False, "This coupon code is inactive."
        if self.valid_from and now < self.valid_from:
            return False, "This coupon code is not active yet."
        if self.valid_until and now > self.valid_until:
            return False, "This coupon code has expired."
        if self.max_redemptions is not None and self.times_redeemed >= self.max_redemptions:
            return False, "This coupon code has reached its redemption limit."
        if (
            target_plan_type
            and self.applicable_plan_type != CouponPlanScope.ALL
            and self.applicable_plan_type != target_plan_type
        ):
            return False, f"This coupon is only valid for {self.applicable_plan_type.title()} plans."
        return True, ""

    def __str__(self):
        return f"{self.code} ({self.get_discount_amount_label()})"


class CouponRedemption(BaseModel):
    """Audit record of a DiscountCoupon applied to a web Stripe checkout or Fleet account."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    coupon = models.ForeignKey(DiscountCoupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coupon_redemptions")
    subscription = models.ForeignKey(
        UserSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coupon_redemptions",
    )
    fleet_account = models.ForeignKey(
        FleetAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coupon_redemptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coupon_redemptions",
    )
    original_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2)
    final_price = models.DecimalField(max_digits=12, decimal_places=2)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.coupon.code} -> {self.user.email} ({self.status})"





