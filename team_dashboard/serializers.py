from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from account.models import User, OTPVerification, Team
from core.constants import OTPPurpose, UserStatus
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS
from team_dashboard.permissions import is_team_dashboard_user, get_team_for_user, get_user_team_permissions
from team_dashboard.utils import generate_and_send_team_otp, mask_email_address


class TeamLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    remember_me = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        email = attrs.get("email", "").strip().lower()
        password = attrs.get("password")

        user = authenticate(username=email, password=password)
        if not user:
            # Also try matching User email directly in case username differs
            user_obj = User.objects.filter(email__iexact=email).first()
            if user_obj and user_obj.check_password(password):
                user = user_obj

        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active or user.status == UserStatus.BLOCKED:
            raise serializers.ValidationError("This account is inactive or blocked. Please contact support.")

        # Verify team access
        team = get_team_for_user(user)
        if not team:
            raise serializers.ValidationError(
                "No active Team or Fleet account found for this user. "
                "The Team Dashboard requires an active Team or Fleet plan."
            )

        attrs["user"] = user
        attrs["team"] = team
        return attrs


class TeamVerifyOTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, max_length=6, min_length=6)

    def validate(self, attrs):
        email = attrs.get("email", "").strip().lower()
        otp_code = attrs.get("otp_code", "").strip()

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise serializers.ValidationError("User account not found.")

        otp_obj = (
            OTPVerification.objects.filter(
                user=user,
                otp_code=otp_code,
                purpose=OTPPurpose.LOGIN,
                is_verified=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj:
            raise serializers.ValidationError("Invalid verification code.")

        if otp_obj.is_expired:
            raise serializers.ValidationError("Verification code has expired. Please request a new code.")

        # Mark OTP verified
        otp_obj.is_verified = True
        otp_obj.verified_at = timezone.now()
        otp_obj.save(update_fields=["is_verified", "verified_at"])

        team = get_team_for_user(user)
        if not team:
            raise serializers.ValidationError("No active Team or Fleet account found.")

        attrs["user"] = user
        attrs["team"] = team
        return attrs


class TeamResendOTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate(self, attrs):
        email = attrs.get("email", "").strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise serializers.ValidationError("User account not found.")

        if not is_team_dashboard_user(user):
            raise serializers.ValidationError("No active Team or Fleet account found for this user.")

        attrs["user"] = user
        return attrs


class TeamInfoSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    used_members_count = serializers.SerializerMethodField()
    plan_name = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "owner_email",
            "max_members",
            "used_members_count",
            "plan_name",
            "is_active",
        ]

    def get_used_members_count(self, obj):
        return obj.members.filter(status=True).count()

    def get_plan_name(self, obj):
        sub = obj.subscriptions.order_by("-created_at").first()
        if sub and sub.plan:
            return sub.plan.name
        return "Team Plan"


class TeamDashboardUserSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="user.id")
    email = serializers.EmailField(source="user.email")
    role = serializers.CharField()
    full_name = serializers.CharField()
    is_super_admin = serializers.BooleanField()
    team = TeamInfoSerializer()
    permissions = serializers.ListField(child=serializers.CharField())


class TeamLoginOTPResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    message = serializers.CharField()
    email = serializers.EmailField()
    masked_email = serializers.CharField()
    next_step = serializers.CharField(default="OTP_VERIFY")


class TeamLoginSuccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    message = serializers.CharField()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    user = serializers.DictField()
    team = TeamInfoSerializer()
    permissions = serializers.ListField(child=serializers.CharField())
