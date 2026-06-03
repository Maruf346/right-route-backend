# validators.py

from subscription.models import UserSubscription
from account.models import TeamMember
from core.constants import UserSubscriptionStatus, TeamMemberStatus, PlanType
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q

class SubscriptionValidator:
    @staticmethod
    def has_valid_subscription(queryset):
        ACTIVE_STATUSES = [UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL]
        now = timezone.now()
        return queryset.filter(
            Q(
                status__in=ACTIVE_STATUSES,
                expires_at__gt=now,
            )
            |
            Q(
                status=UserSubscriptionStatus.GRACE_PERIOD,
                grace_period_until__gt=now,
            )
        )
    
    @classmethod
    def validate_purchase(cls, user):
        mySubscription = UserSubscription.objects.filter(user=user)
        if cls.has_valid_subscription(mySubscription).exists():
            raise ValidationError({
                "detail": f"You already have an active subscription."
            })

        # User belongs to any team
        membership = (
            TeamMember.objects
            .select_related("team", "team__owner")
            .filter(
                user=user,
                status=TeamMemberStatus.ACTIVE
            )
            .first()
        )
        if not membership:
            return True

        # User is owner of that team
        if membership.team.owner_id == user.id:
            return True
        
        # Team has active subscription?
        teamSubscription = UserSubscription.objects.select_related("plan").filter(team=membership.team)
        owner_subscription = (
            cls.has_valid_subscription(
                teamSubscription
            )
            .first()
        )

        # Team subscription validation
        if (owner_subscription and owner_subscription.plan.plan_type == PlanType.TEAM):
            raise ValidationError({
                "detail": "You are already part of another team subscription."
            })
        return True



class TeamMemberValidator:

    @staticmethod
    def get_valid_subscription(team, owner):
        now = timezone.now()
        subscription = UserSubscription.objects.select_related("plan").filter(
            user=owner
        )
        return (
            subscription
            .filter(
                Q(
                    status__in=[
                        UserSubscriptionStatus.ACTIVE,
                        UserSubscriptionStatus.TRIAL,
                    ],
                    expires_at__gt=now
                )
                |
                Q(
                    status=UserSubscriptionStatus.GRACE_PERIOD,
                    grace_period_until__gt=now
                )
            )
            .first()
        )

    @classmethod
    def validate_add_member(cls, owner, target_user):
        team = owner.owned_team

        # User can't add himself
        if owner.id == target_user.id:
            raise ValidationError(
                "You cannot add yourself as a team member."
            )

        # Team subscription exists?
        subscription = cls.get_valid_subscription(team, owner)
        if not subscription:
            raise ValidationError(
                "No active team subscription found."
            )

        # Team plan required
        print("subscription.team: ", subscription.team)
        if subscription.plan.plan_type != PlanType.TEAM or subscription.team or subscription.team != team:
            raise ValidationError(
                "Current subscription does not support team members."
            )

        # Team limit validation
        active_members = team.members.filter(
            status=TeamMemberStatus.ACTIVE
        ).count()

        if active_members >= subscription.plan.team_limit:
            raise ValidationError(
                f"Team member limit reached. "
                f"Maximum allowed: {subscription.plan.team_limit}"
            )

        
        membership = (
            TeamMember.objects
            .select_related("team", "team__owner")
            .filter(
                user=target_user,
                status=TeamMemberStatus.ACTIVE
            )
            .first()
        )
        if membership and membership.team.owner_id != target_user.id:
            raise ValidationError(
                "User already belongs to another team."
            )
        
        # Already member?
        if TeamMember.objects.filter(
            team=team,
            user=target_user
        ).exists():
            raise ValidationError(
                "User is already a member of this team."
            )
        return True

