from django.conf import settings
from django.db import models
from core.common_models import BaseModel
from core.constants import BillingType, PlanType, UserSubscriptionStatus, PaymentStatus
from account.models import UserPaymentMethod, User

class SubscriptionPlan(BaseModel):
    name = models.CharField(max_length=255)
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)
    billing_type = models.CharField(max_length=20, choices=BillingType.choices)
    team_limit = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    features_json = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return self.name

class UserSubscription(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")

    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=30, choices=UserSubscriptionStatus.choices, default=UserSubscriptionStatus.PENDING)
    starts_at = models.DateTimeField()
    last_renew_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    auto_renew = models.BooleanField(default=False)

    payment_status = models.CharField(max_length=50)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["is_active"]),
        ]

class PaymentTransaction(BaseModel):
    user = models.ForeignKey(User,on_delete=models.CASCADE, related_name="payment_transaction")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, related_name="payment_transaction")
    payment_method = models.ForeignKey(UserPaymentMethod, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_transaction")
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    payment_provider = models.CharField(max_length=50)
    provider_transaction_id = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255)
    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

