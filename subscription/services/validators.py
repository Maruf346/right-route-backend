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
        if subscription.plan.plan_type != PlanType.TEAM:
            raise ValidationError(
                "This subscription is not a TEAM plan."
            )

        if subscription.team_id != team.id:
            raise ValidationError(
                "This subscription does not belong to your team."
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

        # Already member?
        if TeamMember.objects.filter(
            team=team,
            user=target_user
        ).exists():
            raise ValidationError(
                "User is already a member of this team."
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
        return True



class RouteAccessValidator:
    @staticmethod
    def get_valid_subscription(user):
        now = timezone.now()
        return (
            UserSubscription.objects
            .select_related("plan", "team")
            .filter(user=user)
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
    def validate_route_creation(cls, user):
        my_subscription = cls.get_valid_subscription(user)
        if my_subscription:
            return True, {
                "access_type": "self",
                "team": None,
                "subscription": my_subscription
            }

        # TEAM MEMBERSHIP CHECK
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
            raise ValidationError(
                "No active subscription found. Route creation not allowed."
            )

        # TEAM OWNER SUBSCRIPTION CHECK
        owner_subscription = cls.get_valid_subscription(
            membership.team.owner
        )

        if not owner_subscription:
            raise ValidationError(
                "Team owner has no active subscription."
            )

        # MUST BE TEAM PLAN
        if owner_subscription.plan.plan_type != PlanType.TEAM:
            raise ValidationError(
                "Team subscription plan is not valid for route creation."
            )
        return True, {
            "access_type": "team",
            "team": membership.team,
            "subscription": owner_subscription
        }

