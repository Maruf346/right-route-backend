from django.conf import settings
from django.db import models
from core.common_models import BaseModel
from core.constants import BillingType, PlanType, UserSubscriptionStatus, PaymentStatus, PaymentTransactionStatus, PURCHASE_VERIFY_STATUS, PURCHASE_PLATFORM
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
    order_id = models.CharField(max_length=255, blank=True, null=True)
    purchase_time = models.DateTimeField()
    expiry_time = models.DateTimeField(blank=True, null=True)
    auto_renew = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=20, choices=PURCHASE_VERIFY_STATUS.choices, default=PURCHASE_VERIFY_STATUS.PENDING)
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)





