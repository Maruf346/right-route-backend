from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from subscription.models import UserSubscription, SubscriptionPlan
from account.models import Team
from .validators import SubscriptionValidator
from core.constants import PlanType, UserSubscriptionStatus, PaymentStatus
import uuid

class SubscriptionPurchaseService:
    @classmethod
    @transaction.atomic
    def create_pending_subscription(
        cls,
        *,
        user,
        plan: SubscriptionPlan
    ):
        SubscriptionValidator.validate_purchase(user)
        
        if plan.plan_type == PlanType.TEAM:
            team = getattr(user, "owned_team", None)
            if plan.plan_type == PlanType.TEAM and not team:
                raise Exception(
                    "No team found for this user."
                )
            subscription = UserSubscription.objects.create(
                user=user,
                team=team,
                plan=plan,
                status=UserSubscriptionStatus.PENDING,
                starts_at=timezone.now(),
                last_renew_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=30),
                payment_status=PaymentStatus.PENDING
            )
        elif plan.plan_type == PlanType.INDIVIDUAL:
            subscription = UserSubscription.objects.create(
                user=user,
                plan=plan,
                status=UserSubscriptionStatus.PENDING,
                starts_at=timezone.now(),
                last_renew_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=30),
                payment_status=PaymentStatus.PENDING
            )
        else:
            raise Exception("User Subscription Failed!")
        return subscription