from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from account.models import User, OTPVerification, Team
from core.constants import OTPPurpose, UserStatus
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS
from team_dashboard.permissions import is_team_dashboard_user, get_team_for_user, get_user_team_permissions
from team_dashboard.utils import (
    generate_and_send_team_otp,
    is_team_login_otp_expired,
    mask_email_address,
)
from route.service import normalize_state_code


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

        # Team Dashboard access is controlled by an active admin profile or
        # team ownership. Do not fall back to ordinary driver membership here.
        if not is_team_dashboard_user(user):
            raise serializers.ValidationError(
                "Your Team Dashboard access is locked or inactive. Please contact your team administrator."
            )

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

        # Re-check access at OTP verification time in case an administrator
        # was locked after requesting the code but before submitting it.
        if not is_team_dashboard_user(user):
            raise serializers.ValidationError(
                "Your Team Dashboard access is locked or inactive. Please contact your team administrator."
            )

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

        if is_team_login_otp_expired(otp_obj):
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
    expires_in_seconds = serializers.IntegerField(default=900)


class TeamLoginUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    role = serializers.CharField()
    is_super_admin = serializers.BooleanField()


class TeamLoginSuccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    message = serializers.CharField()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    user = TeamLoginUserSerializer()
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


class TeamManageOTPResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    masked_email = serializers.CharField()
    action = serializers.ChoiceField(choices=["CHANGE_EMAIL", "CHANGE_PASSWORD"])
    expires_in_seconds = serializers.IntegerField()


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

    def validate_users(self, value):
        normalized = [item["email"].strip().casefold() for item in value]
        duplicates = sorted({email for email in normalized if normalized.count(email) > 1})
        if duplicates:
            raise serializers.ValidationError(
                f"Duplicate emails in request: {', '.join(duplicates)}"
            )
        return value


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

    def validate_member_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Member IDs must be unique.")
        return value


class TeamMemberBulkInviteSerializer(TeamMemberBulkRemoveSerializer):
    pass


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

class TeamUsersPaginationSerializer(serializers.Serializer):
    current_page = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    total_count = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()


class TeamUsersListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    plan_stats = TeamUsersStatsSerializer()
    pagination = TeamUsersPaginationSerializer()
    results = TeamMemberItemSerializer(many=True)


class TeamUsersProcessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    added_count = serializers.IntegerField()
    updated_count = serializers.IntegerField()


class TeamUsersInviteFailureResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    detail = serializers.CharField()
    added_count = serializers.IntegerField()
    updated_count = serializers.IntegerField()


class TeamUsersInviteSummarySerializer(serializers.Serializer):
    message = serializers.CharField()
    queued_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    failures = serializers.ListField(child=serializers.DictField())
    idempotent_count = serializers.IntegerField(required=False)


class TeamUsersImportResponseSerializer(TeamUsersProcessResponseSerializer):
    errors = serializers.ListField(child=serializers.CharField())


class TeamAdminGeneratePasswordResponseSerializer(serializers.Serializer):
    password = serializers.CharField()


class TeamUsersImportCSVRequestSerializer(serializers.Serializer):
    file = serializers.FileField()


class PermissionTreeChildSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class PermissionTreeNodeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    children = PermissionTreeChildSerializer(many=True, required=False)


class TeamPermissionTreeResponseSerializer(serializers.Serializer):
    permission_tree = PermissionTreeNodeSerializer(many=True)
    all_permissions = serializers.ListField(child=serializers.CharField())




class TeamRouteWaypointWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    index = serializers.IntegerField(required=False, min_value=1)
    name = serializers.CharField(required=True, max_length=255)
    waypoint_type = serializers.CharField(required=False, default="CHECKPOINT")
    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    icon = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    eta_minutes = serializers.IntegerField(required=False, min_value=0, default=0)


class TeamRoutePermitWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    index = serializers.IntegerField(required=False, min_value=1)
    name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    permit_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    issuing_state = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=30)
    start_location = serializers.CharField(required=True, allow_blank=True, max_length=255)
    start_latitude = serializers.FloatField(required=True)
    start_longitude = serializers.FloatField(required=True)
    end_location = serializers.CharField(required=True, allow_blank=True, max_length=255)
    end_latitude = serializers.FloatField(required=True)
    end_longitude = serializers.FloatField(required=True)
    permit_file = serializers.FileField(required=False)
    permit_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    waypoints = TeamRouteWaypointWriteSerializer(many=True, required=False)

    def validate_issuing_state(self, value):
        if not value:
            return None
        state_code = normalize_state_code(value)
        if not state_code:
            raise serializers.ValidationError("Use a valid US state name or two-letter abbreviation.")
        return state_code

    def validate_waypoints(self, value):
        indexes = [item.get("index") for item in value if item.get("index") is not None]
        if len(indexes) != len(set(indexes)):
            raise serializers.ValidationError("Waypoint indexes must be unique within a permit.")
        return value


def _validate_permit_chain(permits, route_data=None):
    """Validate ordered permit boundaries before anything is written to the database."""
    if not permits:
        return permits

    indexes = [item.get("index") for item in permits if item.get("index") is not None]
    if len(indexes) != len(set(indexes)):
        raise serializers.ValidationError({"permits": "Permit indexes must be unique."})
    if indexes and sorted(indexes) != list(range(1, len(permits) + 1)):
        raise serializers.ValidationError({"permits": "Permit indexes must be contiguous starting at 1."})

    ordered = sorted(
        enumerate(permits),
        key=lambda entry: (entry[1].get("index") or entry[0] + 1),
    )
    tolerance = 0.0001
    for position in range(1, len(ordered)):
        previous = ordered[position - 1][1]
        current = ordered[position][1]
        lat_matches = abs(previous["end_latitude"] - current["start_latitude"]) <= tolerance
        lng_matches = abs(previous["end_longitude"] - current["start_longitude"]) <= tolerance
        if not (lat_matches and lng_matches):
            current_index = current.get("index") or position + 1
            previous_index = previous.get("index") or position
            raise serializers.ValidationError({
                "permits": (
                    f"Permit {current_index} start coordinates must match "
                    f"Permit {previous_index} end coordinates."
                )
            })

    if route_data:
        first = ordered[0][1]
        last = ordered[-1][1]
        pairs = (
            (first["start_latitude"], route_data.get("start_latitude")),
            (first["start_longitude"], route_data.get("start_longitude")),
            (last["end_latitude"], route_data.get("end_latitude")),
            (last["end_longitude"], route_data.get("end_longitude")),
        )
        if any(expected is not None and abs(actual - expected) > tolerance for actual, expected in pairs):
            raise serializers.ValidationError({
                "permits": "The first/last permit boundaries must match the route start/end coordinates."
            })
    return permits


class TeamRouteCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    start_location = serializers.CharField(required=True, allow_blank=True, max_length=255)
    start_latitude = serializers.FloatField(required=True)
    start_longitude = serializers.FloatField(required=True)
    end_location = serializers.CharField(required=True, allow_blank=True, max_length=255)
    end_latitude = serializers.FloatField(required=True)
    end_longitude = serializers.FloatField(required=True)
    permit_file = serializers.FileField(required=False)
    permit_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    waypoints = TeamRouteWaypointWriteSerializer(many=True, required=False)
    permits = TeamRoutePermitWriteSerializer(many=True, required=False)

    def validate(self, attrs):
        permits = attrs.get("permits")
        if permits is not None:
            if not permits:
                raise serializers.ValidationError({"permits": "At least one permit is required when permits is supplied."})
            if attrs.get("permit_file") or attrs.get("permit_text") or attrs.get("waypoints"):
                raise serializers.ValidationError(
                    "Use either the nested permits payload or the legacy flat permit fields, not both."
                )
            _validate_permit_chain(permits, attrs)
        return attrs


class TeamRouteUpdateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    status = serializers.CharField(required=False)
    is_completed = serializers.BooleanField(required=False)
    total_distance_km = serializers.FloatField(required=False, min_value=0)
    estimated_duration = serializers.IntegerField(required=False, min_value=0)


class TeamRouteMapUpdateRequestSerializer(TeamRouteUpdateRequestSerializer):
    permits = TeamRoutePermitWriteSerializer(many=True, required=False)
    delete_missing_permits = serializers.BooleanField(required=False, default=False)
    replace_waypoints = serializers.BooleanField(required=False, default=True)

    def validate_permits(self, value):
        return _validate_permit_chain(value)


class TeamPermitParseRequestSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    permit_text = serializers.CharField(required=False, allow_blank=False)
    state_hint = serializers.CharField(required=False, allow_blank=False, max_length=30)

    def validate_state_hint(self, value):
        state_code = normalize_state_code(value)
        if not state_code:
            raise serializers.ValidationError("Use a valid US state name or two-letter abbreviation.")
        return state_code

    def validate_file(self, value):
        extension = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
        if extension not in {"pdf", "png", "jpg", "jpeg"}:
            raise serializers.ValidationError("Supported permit files are PDF, PNG, JPG, and JPEG.")
        if value.size > 20 * 1024 * 1024:
            raise serializers.ValidationError("Permit files may not exceed 20 MB.")
        return value

    def validate(self, attrs):
        supplied = int(bool(attrs.get("file"))) + int(bool(attrs.get("permit_text")))
        if supplied != 1:
            raise serializers.ValidationError("Provide exactly one of file or permit_text.")
        return attrs


class TeamPermitParsedLocationSerializer(serializers.Serializer):
    name = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class TeamPermitParsedWaypointSerializer(TeamPermitParsedLocationSerializer):
    index = serializers.IntegerField()
    waypoint_type = serializers.CharField()


class TeamPermitParseResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    permit_number = serializers.CharField(allow_null=True, required=False)
    issuing_state = serializers.CharField()
    origin = TeamPermitParsedLocationSerializer(allow_null=True)
    destination = TeamPermitParsedLocationSerializer(allow_null=True)
    waypoints = TeamPermitParsedWaypointSerializer(many=True)
    unresolved_waypoints = serializers.ListField(child=serializers.CharField())


class TeamRouteMutationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    route_id = serializers.IntegerField()


class TeamRoutePermitMutationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    permit_id = serializers.IntegerField(required=False)


class TeamRouteWaypointMutationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    waypoint_id = serializers.IntegerField(required=False)
