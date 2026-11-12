from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from subscription.models import UserSubscription, SubscriptionPlan
from account.models import Team
from .validators import SubscriptionValidator
from core.constants import PlanType, BillingType, UserSubscriptionStatus, PaymentStatus
import uuid

class SubscriptionPurchaseService:
    @staticmethod
    def get_plan_duration(plan):
        if getattr(plan, "trial_days", 0) and plan.trial_days > 0:
            return timedelta(days=plan.trial_days)
        if plan.billing_type == BillingType.YEARLY:
            return timedelta(days=365)
        return timedelta(days=30)

    @classmethod
    @transaction.atomic
    def create_pending_subscription(
        cls,
        *,
        user,
        plan: SubscriptionPlan
    ):
        SubscriptionValidator.validate_purchase(user, plan=plan)

        # Clean up stale unverified pending attempts so aborted checkouts do not clutter user history
        UserSubscription.objects.filter(
            user=user,
            status=UserSubscriptionStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
        ).delete()

        now = timezone.now()
        team = None
        if plan.plan_type == PlanType.TEAM:
            team = getattr(user, "owned_team", None)
            if not team:
                team_prefix = (user.email or f"user-{user.id}").split("@")[0]
                team, _ = Team.objects.get_or_create(
                    owner=user,
                    defaults={
                        "name": f"{team_prefix}'s Team",
                        "max_members": plan.team_limit or 0,
                    },
                )
            subscription = UserSubscription.objects.create(
                user=user,
                team=team,
                plan=plan,
                status=UserSubscriptionStatus.PENDING,
                starts_at=now,
                last_renew_at=now,
                expires_at=now + cls.get_plan_duration(plan),
                payment_status=PaymentStatus.PENDING,
            )
        elif plan.plan_type == PlanType.INDIVIDUAL:
            subscription = UserSubscription.objects.create(
                user=user,
                plan=plan,
                status=UserSubscriptionStatus.PENDING,
                starts_at=now,
                last_renew_at=now,
                expires_at=now + cls.get_plan_duration(plan),
                payment_status=PaymentStatus.PENDING,
            )
        else:
            raise Exception("User Subscription Failed!")
        return subscription


