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


# ==========================================
# 1. MANAGE — EMAIL / PASSWORD SERIALIZERS
# ==========================================

class TeamSendManageOTPRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["CHANGE_EMAIL", "CHANGE_PASSWORD"],
        default="CHANGE_EMAIL",
        help_text="Action to verify (CHANGE_EMAIL or CHANGE_PASSWORD)",
    )


class TeamChangeEmailRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    current_password = serializers.CharField(required=True, write_only=True)
    otp_code = serializers.CharField(required=True, max_length=6, min_length=6)

    def validate_new_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email address is already in use by another account.")
        return value


class TeamChangePasswordRequestSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, min_length=8, write_only=True)
    confirm_password = serializers.CharField(required=True, min_length=8, write_only=True)
    otp_code = serializers.CharField(required=True, max_length=6, min_length=6)

    def validate(self, attrs):
        if attrs.get("new_password") != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "New passwords do not match."})
        return attrs


# ==========================================
# 2. MANAGE — ADMIN USERS SERIALIZERS
# ==========================================

class TeamAdminUserListSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="user.id")
    profile_id = serializers.IntegerField(source="id")
    full_name = serializers.CharField()
    email = serializers.EmailField(source="user.email")
    phone = serializers.CharField(allow_null=True, allow_blank=True)
    role = serializers.CharField()
    role_label = serializers.CharField()
    user_id_display = serializers.CharField()
    is_active = serializers.BooleanField()
    access_status = serializers.SerializerMethodField()
    is_super_admin = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_access_status(self, obj):
        return "Active" if obj.is_active else "Locked out"

    def get_is_super_admin(self, obj):
        return obj.role == TeamDashboardRole.SUPER_ADMIN or getattr(obj.team, "owner_id", None) == obj.user_id


class TeamAdminUserDetailSerializer(TeamAdminUserListSerializer):
    permissions_json = serializers.ListField(child=serializers.CharField(), default=list)


class TeamAdminUserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=True, max_length=255)
    email = serializers.EmailField(required=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50, default="")
    role_label = serializers.CharField(required=False, allow_blank=True, max_length=100, default="Team Admin")
    password = serializers.CharField(required=True, min_length=8, write_only=True)
    permissions_json = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="List of granted permission strings (e.g. ['manage.team_users', 'support.contact_support'])",
    )

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email address already exists.")
        return value


class TeamAdminUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, max_length=255)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    role_label = serializers.CharField(required=False, allow_blank=True, max_length=100)
    password = serializers.CharField(required=False, allow_blank=True, min_length=8, write_only=True)
    permissions_json = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Updated list of granted permission strings",
    )
    is_active = serializers.BooleanField(required=False)


class TeamAdminBulkActionSerializer(serializers.Serializer):
    admin_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        min_length=1,
        help_text="List of User IDs to apply action to",
    )
    action = serializers.ChoiceField(
        choices=["delete", "lock", "unlock"],
        required=True,
        help_text="Action to perform on selected admin users",
    )


# ==========================================
# 3. MANAGE — TEAM USERS (DRIVERS) SERIALIZERS
# ==========================================

class TeamMemberItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_id = serializers.IntegerField(source="user.id")
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email")
    is_enrolled = serializers.BooleanField(source="status")
    enrolled_display = serializers.SerializerMethodField()
    joined_at = serializers.DateTimeField()

    def get_name(self, obj):
        if obj.username:
            return obj.username
        return obj.user.email.split("@")[0]

    def get_enrolled_display(self, obj):
        return "Yes" if obj.status else "No"


class SingleMemberInputSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=255)
    email = serializers.EmailField(required=True)


class TeamMemberBatchAddSerializer(serializers.Serializer):
    users = serializers.ListField(
        child=SingleMemberInputSerializer(),
        required=True,
        min_length=1,
        help_text="List of users to add: [{'name': 'John Doe', 'email': 'john@example.com'}]",
    )


class TeamMemberUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255)
    email = serializers.EmailField(required=False)


class TeamMemberBulkRemoveSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        min_length=1,
        help_text="List of TeamMember IDs to remove from the team",
    )


class TeamUsersStatsSerializer(serializers.Serializer):
    max_members = serializers.IntegerField()
    total_in_list = serializers.IntegerField()
    enrolled_count = serializers.IntegerField()
    not_enrolled_count = serializers.IntegerField()
    slots_remaining = serializers.IntegerField()


# ==========================================
# 4. MANAGE — ROUTE HISTORY SERIALIZERS
# ==========================================

class RouteHistoryItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    route_number = serializers.SerializerMethodField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField()
    created_at_formatted = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    driver_email = serializers.EmailField(source="created_by.email")
    total_distance_km = serializers.FloatField()
    total_waypoints = serializers.IntegerField()
    status = serializers.CharField()
    is_completed = serializers.BooleanField()

    def get_route_number(self, obj):
        # Format as #010, #009 based on sequence or ID
        seq = getattr(obj, "_route_sequence_number", None)
        if seq is not None:
            return f"#{seq:03d}"
        return f"#{obj.id:03d}"

    def get_created_at_formatted(self, obj):
        if obj.created_at:
            return obj.created_at.strftime("%b %d, %Y")
        return ""

    def get_driver_name(self, obj):
        driver = obj.created_by
        return driver.email.split("@")[0]


class RouteWaypointItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    index = serializers.IntegerField()
    name = serializers.CharField()
    waypoint_type = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    eta_minutes = serializers.IntegerField()
    description = serializers.CharField(allow_blank=True, allow_null=True)
    icon = serializers.CharField(allow_blank=True, allow_null=True)


class RouteHistoryBulkDeleteSerializer(serializers.Serializer):
    route_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        min_length=1,
        help_text="List of Route IDs to delete",
    )


# ==========================================
# 5. MANAGE — PLAN SERIALIZERS
# ==========================================

class TeamPlanDetailSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    owner_email = serializers.EmailField()
    plan_name = serializers.CharField()
    billing_frequency = serializers.CharField()
    renewal_date = serializers.CharField(allow_null=True)
    max_users_allowed = serializers.IntegerField()
    total_enrolled_users = serializers.IntegerField()
    total_registered_users = serializers.IntegerField()
    slots_remaining = serializers.IntegerField()
    is_active = serializers.BooleanField()

