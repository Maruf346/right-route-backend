from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.db.models import Q

from team_dashboard.permissions import (
    IsTeamDashboardUser,
    IsTeamSuperAdmin,
    HasTeamDashboardPermission,
    get_team_for_user,
    get_user_team_permissions,
    is_team_super_admin,
)
from team_dashboard.utils import (
    generate_and_send_team_otp,
    mask_email_address,
)
from team_dashboard.serializers import (
    # Auth
    TeamLoginRequestSerializer,
    TeamVerifyOTPRequestSerializer,
    TeamResendOTPRequestSerializer,
    TeamInfoSerializer,
    TeamLoginOTPResponseSerializer,
    TeamLoginSuccessResponseSerializer,
    TeamDashboardUserSessionSerializer,
    # Manage — Email/Password
    TeamSendManageOTPRequestSerializer,
    TeamChangeEmailRequestSerializer,
    TeamChangePasswordRequestSerializer,
    # Manage — Admin Users
    TeamAdminUserListSerializer,
    TeamAdminUserDetailSerializer,
    TeamAdminUserCreateSerializer,
    TeamAdminUserUpdateSerializer,
    TeamAdminBulkActionSerializer,
    # Manage — Team Users
    TeamMemberItemSerializer,
    TeamMemberBatchAddSerializer,
    TeamMemberUpdateSerializer,
    TeamMemberBulkRemoveSerializer,
    TeamUsersStatsSerializer,
    # Manage — Route History
    RouteHistoryItemSerializer,
    RouteWaypointItemSerializer,
    RouteHistoryBulkDeleteSerializer,
    # Manage — Plan
    TeamPlanDetailSerializer,
)
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS



@extend_schema(
    tags=["Team Dashboard - Auth"],
    summary="Step 1: Team Dashboard Login (Credentials -> MFA Code Sent)",
    description=(
        "Validates team account credentials (email and password). "
        "Upon successful validation, a 6-digit verification code is emailed to the user."
    ),
    request=TeamLoginRequestSerializer,
    responses={
        200: TeamLoginOTPResponseSerializer,
        400: OpenApiResponse(description="Invalid credentials or inactive team account."),
    },
)
class TeamLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TeamLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        # Generate and send 6-digit MFA verification code
        generate_and_send_team_otp(user, request)

        masked_email = mask_email_address(user.email)
        return Response(
            {
                "success": True,
                "message": "Verification code sent to your email address.",
                "email": user.email,
                "masked_email": masked_email,
                "next_step": "OTP_VERIFY",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Auth"],
    summary="Step 2: Team Dashboard Verify OTP (MFA Code -> JWT Tokens & Permissions)",
    description=(
        "Verifies the 6-digit code received via email. "
        "Upon success, returns JWT access and refresh tokens, team details, role, and granted section permissions."
    ),
    request=TeamVerifyOTPRequestSerializer,
    responses={
        200: TeamLoginSuccessResponseSerializer,
        400: OpenApiResponse(description="Invalid or expired verification code."),
    },
)
class TeamVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TeamVerifyOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        team = serializer.validated_data["team"]

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        # Determine role and permissions
        is_owner = (team.owner_id == user.id)
        role = TeamDashboardRole.SUPER_ADMIN if is_owner else TeamDashboardRole.ADMIN
        profile = getattr(user, "team_admin_profile", None)
        if profile and not is_owner:
            role = profile.role

        permissions = get_user_team_permissions(user)
        full_name = getattr(profile, "full_name", None) or user.email.split("@")[0]

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "access_token": access,
                "refresh_token": str(refresh),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": full_name,
                    "role": role,
                    "is_super_admin": is_owner or role == TeamDashboardRole.SUPER_ADMIN,
                },
                "team": TeamInfoSerializer(team).data,
                "permissions": permissions,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Auth"],
    summary="Resend Team Dashboard Verification Code",
    description="Resends a fresh 6-digit MFA verification code to the user's email address.",
    request=TeamResendOTPRequestSerializer,
    responses={
        200: TeamLoginOTPResponseSerializer,
        400: OpenApiResponse(description="User account or active team not found."),
    },
)
class TeamResendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TeamResendOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        generate_and_send_team_otp(user, request)

        masked_email = mask_email_address(user.email)
        return Response(
            {
                "success": True,
                "message": "A new verification code has been sent to your email address.",
                "email": user.email,
                "masked_email": masked_email,
                "next_step": "OTP_VERIFY",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Auth"],
    summary="Get Authenticated Team Dashboard Session & Permissions",
    description="Returns current authenticated user details, team details, role, and granted sidebar permissions.",
    responses={200: TeamDashboardUserSessionSerializer},
)
class TeamSessionView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser]

    def get(self, request):
        user = request.user
        team = get_team_for_user(user)

        is_owner = (team.owner_id == user.id) if team else False
        role = TeamDashboardRole.SUPER_ADMIN if is_owner else TeamDashboardRole.ADMIN
        profile = getattr(user, "team_admin_profile", None)
        if profile and not is_owner:
            role = profile.role

        permissions = get_user_team_permissions(user)
        full_name = getattr(profile, "full_name", None) or user.email.split("@")[0]

        data = {
            "id": user.id,
            "email": user.email,
            "role": role,
            "full_name": full_name,
            "is_super_admin": is_owner or role == TeamDashboardRole.SUPER_ADMIN,
            "team": TeamInfoSerializer(team).data if team else None,
            "permissions": permissions,
        }
        return Response(data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Auth"],
    summary="Logout from Team Dashboard",
    responses={200: OpenApiResponse(description="Logout successful.")},
)
class TeamLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Optional: blacklist refresh token if provided
        refresh_token = request.data.get("refresh_token")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        return Response({"success": True, "message": "Logout successful."}, status=status.HTTP_200_OK)


# =====================================================================
# 1. MANAGE — EMAIL & PASSWORD VIEWS
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Manage"],
    summary="Send Verification Code for Email/Password Change",
    description="Sends a 6-digit OTP to the current logged-in user's email to verify account changes.",
    request=TeamSendManageOTPRequestSerializer,
    responses={200: OpenApiResponse(description="Verification code sent successfully.")},
)
class TeamManageSendOTPView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.email_password"

    def post(self, request):
        serializer = TeamSendManageOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data.get("action", "CHANGE_EMAIL")
        action_label = "Email Change" if action == "CHANGE_EMAIL" else "Password Change"

        from team_dashboard.utils import generate_and_send_manage_otp
        generate_and_send_manage_otp(request.user, action_label=action_label, request=request)

        masked_email = mask_email_address(request.user.email)
        return Response(
            {
                "success": True,
                "message": f"Verification code sent to {masked_email}.",
                "masked_email": masked_email,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage"],
    summary="Change Email (Requires OTP + Current Password)",
    description="Verifies the current password and 6-digit OTP before updating the user's email address.",
    request=TeamChangeEmailRequestSerializer,
    responses={
        200: OpenApiResponse(description="Email changed successfully."),
        400: OpenApiResponse(description="Validation error, invalid password, or invalid OTP."),
    },
)
class TeamManageChangeEmailView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.email_password"

    def post(self, request):
        from account.models import OTPVerification
        from core.constants import OTPPurpose
        from django.utils import timezone

        serializer = TeamChangeEmailRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_password = serializer.validated_data["current_password"]
        new_email = serializer.validated_data["new_email"]
        otp_code = serializer.validated_data["otp_code"]

        if not user.check_password(current_password):
            return Response(
                {"success": False, "message": "Incorrect current password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_obj = (
            OTPVerification.objects.filter(
                user=user,
                otp_code=otp_code,
                purpose=OTPPurpose.RESET,
                is_verified=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj or otp_obj.is_expired:
            return Response(
                {"success": False, "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_obj.is_verified = True
        otp_obj.verified_at = timezone.now()
        otp_obj.save(update_fields=["is_verified", "verified_at"])

        old_email = user.email
        user.email = new_email
        user.username = new_email
        user.save(update_fields=["email", "username"])

        return Response(
            {
                "success": True,
                "message": "Email address changed successfully.",
                "email": user.email,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage"],
    summary="Change Password (Requires OTP + Current Password)",
    description="Verifies the current password, 6-digit OTP, and matches new password before updating.",
    request=TeamChangePasswordRequestSerializer,
    responses={
        200: OpenApiResponse(description="Password changed successfully."),
        400: OpenApiResponse(description="Validation error, incorrect password, or invalid OTP."),
    },
)
class TeamManageChangePasswordView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.email_password"

    def post(self, request):
        from account.models import OTPVerification
        from core.constants import OTPPurpose
        from django.utils import timezone

        serializer = TeamChangePasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]
        otp_code = serializer.validated_data["otp_code"]

        if not user.check_password(current_password):
            return Response(
                {"success": False, "message": "Incorrect current password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_obj = (
            OTPVerification.objects.filter(
                user=user,
                otp_code=otp_code,
                purpose=OTPPurpose.RESET,
                is_verified=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj or otp_obj.is_expired:
            return Response(
                {"success": False, "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_obj.is_verified = True
        otp_obj.verified_at = timezone.now()
        otp_obj.save(update_fields=["is_verified", "verified_at"])

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {"success": True, "message": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


# =====================================================================
# 2. MANAGE — ADMIN USERS VIEWS (Super Admin Only)
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="List or Create Admin Users",
    description=(
        "Lists team admin users (GET) or creates a new sub-admin with assigned permissions (POST). "
        "Super Admin privileges required."
    ),
    responses={
        200: TeamAdminUserListSerializer(many=True),
        201: TeamAdminUserDetailSerializer,
    },
)
class TeamAdminUsersListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def get(self, request):
        team = get_team_for_user(request.user)
        if not team:
            return Response([], status=status.HTTP_200_OK)

        from team_dashboard.models import TeamAdminProfile
        from django.db.models import Q

        # Ensure owner has a profile entry for consistent listing
        if not TeamAdminProfile.objects.filter(user=team.owner, team=team).exists():
            TeamAdminProfile.objects.create(
                user=team.owner,
                team=team,
                role=TeamDashboardRole.SUPER_ADMIN,
                role_label="Super Admin",
                full_name=team.owner.email.split("@")[0],
                phone="",
                is_active=True,
            )

        profiles = TeamAdminProfile.objects.filter(team=team).select_related("user", "team")

        # Filters
        search_query = request.query_params.get("search") or request.query_params.get("q")
        if search_query:
            search_query = search_query.strip()
            profiles = profiles.filter(
                Q(full_name__icontains=search_query)
                | Q(user__email__icontains=search_query)
                | Q(role_label__icontains=search_query)
                | Q(user_id_display__icontains=search_query)
            )

        status_param = request.query_params.get("status")
        if status_param == "active":
            profiles = profiles.filter(is_active=True)
        elif status_param in ["locked", "inactive"]:
            profiles = profiles.filter(is_active=False)

        serializer = TeamAdminUserListSerializer(profiles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Adding admin users requires manage.admin_users.add or Super Admin
        from team_dashboard.permissions import is_team_super_admin, get_user_team_permissions
        if not is_team_super_admin(request.user):
            perms = get_user_team_permissions(request.user)
            if "manage.admin_users.add" not in perms:
                return Response(
                    {"detail": "You do not have permission to add admin users."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        team = get_team_for_user(request.user)
        if not team:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamAdminUserCreateSerializer, TeamAdminUserDetailSerializer
        from team_dashboard.models import TeamAdminProfile
        from account.models import User
        from core.constants import UserType

        serializer = TeamAdminUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        full_name = serializer.validated_data["full_name"]
        email = serializer.validated_data["email"]
        phone = serializer.validated_data.get("phone", "")
        role_label = serializer.validated_data.get("role_label") or "Team Admin"
        password = serializer.validated_data["password"]
        permissions_json = serializer.validated_data.get("permissions_json", [])

        # Create user account (User model only holds email, user_type, is_active)
        new_user = User.objects.create(
            email=email,
            user_type=UserType.MAIN_USER,
            is_active=True,
        )
        new_user.set_password(password)
        new_user.save()

        # Create TeamAdminProfile
        profile = TeamAdminProfile.objects.create(
            user=new_user,
            team=team,
            role=TeamDashboardRole.ADMIN,
            role_label=role_label,
            full_name=full_name,
            phone=phone,
            permissions_json=permissions_json,
            created_by=request.user,
            is_active=True,
        )

        return Response(TeamAdminUserDetailSerializer(profile).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="Get, Update, or Delete Single Admin User",
    description="Manage details, role, permissions, and status of a specific admin user.",
)
class TeamAdminUserDetailView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def get_profile(self, request, user_id):
        team = get_team_for_user(request.user)
        from team_dashboard.models import TeamAdminProfile
        return TeamAdminProfile.objects.filter(user_id=user_id, team=team).select_related("user", "team").first()

    def get(self, request, user_id):
        profile = self.get_profile(request, user_id)
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamAdminUserDetailSerializer
        return Response(TeamAdminUserDetailSerializer(profile).data, status=status.HTTP_200_OK)

    def patch(self, request, user_id):
        profile = self.get_profile(request, user_id)
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamAdminUserUpdateSerializer, TeamAdminUserDetailSerializer
        serializer = TeamAdminUserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        full_name = serializer.validated_data.get("full_name")
        phone = serializer.validated_data.get("phone")
        role_label = serializer.validated_data.get("role_label")
        password = serializer.validated_data.get("password")
        permissions_json = serializer.validated_data.get("permissions_json")
        is_active = serializer.validated_data.get("is_active")

        if full_name is not None:
            profile.full_name = full_name

        if phone is not None:
            profile.phone = phone

        if role_label is not None:
            profile.role_label = role_label

        if permissions_json is not None:
            # Cannot remove permissions from team owner
            if profile.user_id != profile.team.owner_id:
                profile.permissions_json = permissions_json

        if is_active is not None:
            if profile.user_id == request.user.id:
                return Response({"detail": "You cannot change your own active status."}, status=status.HTTP_400_BAD_REQUEST)
            if profile.user_id == profile.team.owner_id:
                return Response({"detail": "Cannot modify owner's active status."}, status=status.HTTP_400_BAD_REQUEST)
            profile.is_active = is_active

        if password:
            profile.user.set_password(password)
            profile.user.save(update_fields=["password"])

        profile.updated_by = request.user
        profile.save()

        return Response(TeamAdminUserDetailSerializer(profile).data, status=status.HTTP_200_OK)

    def delete(self, request, user_id):
        profile = self.get_profile(request, user_id)
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        if profile.user_id == request.user.id:
            return Response({"detail": "You cannot delete your own admin account."}, status=status.HTTP_400_BAD_REQUEST)

        if profile.user_id == profile.team.owner_id:
            return Response({"detail": "Cannot delete the Team Owner."}, status=status.HTTP_400_BAD_REQUEST)

        # Revoke access by deleting TeamAdminProfile and setting user is_active=False
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        profile.delete()

        return Response({"success": True, "message": "Admin user deleted successfully."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="Lock Out Admin User",
    description="Locks an admin user account so they cannot log in to the dashboard.",
)
class TeamAdminUserLockView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def post(self, request, user_id):
        team = get_team_for_user(request.user)
        from team_dashboard.models import TeamAdminProfile

        profile = TeamAdminProfile.objects.filter(user_id=user_id, team=team).first()
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        if profile.user_id == request.user.id:
            return Response({"detail": "You cannot lock out your own account."}, status=status.HTTP_400_BAD_REQUEST)
        if profile.user_id == team.owner_id:
            return Response({"detail": "Cannot lock out the Team Owner."}, status=status.HTTP_400_BAD_REQUEST)

        profile.is_active = False
        profile.updated_by = request.user
        profile.save(update_fields=["is_active", "updated_by"])

        return Response({"success": True, "message": f"{profile.full_name or profile.user.email} locked out successfully."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="Unlock Admin User",
    description="Unlocks a previously locked admin user account.",
)
class TeamAdminUserUnlockView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def post(self, request, user_id):
        team = get_team_for_user(request.user)
        from team_dashboard.models import TeamAdminProfile

        profile = TeamAdminProfile.objects.filter(user_id=user_id, team=team).first()
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        profile.is_active = True
        profile.updated_by = request.user
        profile.save(update_fields=["is_active", "updated_by"])

        return Response({"success": True, "message": f"{profile.full_name or profile.user.email} unlocked successfully."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="Bulk Action for Admin Users (Delete / Lock / Unlock)",
    description="Performs bulk delete, lock, or unlock on selected admin user IDs.",
    request=TeamAdminBulkActionSerializer,
    responses={200: OpenApiResponse(description="Bulk action executed successfully.")},
)
class TeamAdminUserBulkActionView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def post(self, request):
        team = get_team_for_user(request.user)
        serializer = TeamAdminBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        admin_ids = serializer.validated_data["admin_ids"]
        action = serializer.validated_data["action"]

        from team_dashboard.models import TeamAdminProfile
        profiles = TeamAdminProfile.objects.filter(
            user_id__in=admin_ids,
            team=team,
        ).exclude(user_id=request.user.id).exclude(user_id=team.owner_id)

        count = 0
        if action == "lock":
            count = profiles.update(is_active=False)
        elif action == "unlock":
            count = profiles.update(is_active=True)
        elif action == "delete":
            count = profiles.count()
            for p in profiles:
                p.user.is_active = False
                p.user.save(update_fields=["is_active"])
                p.delete()

        return Response(
            {
                "success": True,
                "message": f"Action '{action}' applied to {count} admin users.",
                "affected_count": count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Admin Users"],
    summary="Generate Secure Random Password",
    description="Returns a cryptographically secure random password string for new admin users.",
)
class TeamAdminGeneratePasswordView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser]

    def get(self, request):
        from team_dashboard.utils import generate_secure_password
        pwd = generate_secure_password(length=14)
        return Response({"password": pwd}, status=status.HTTP_200_OK)


# =====================================================================
# 3. MANAGE — TEAM USERS (DRIVERS) VIEWS
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="List Team Members & Plan Quota",
    description="Returns the list of drivers/members for this team along with plan slot statistics.",
)
class TeamUsersListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def get(self, request):
        team = get_team_for_user(request.user)
        if not team:
            return Response({"members": [], "plan_stats": {}}, status=status.HTTP_200_OK)

        from account.models import TeamMember
        from django.db.models import Q
        from team_dashboard.serializers import TeamMemberItemSerializer, TeamUsersStatsSerializer
        from django.core.paginator import Paginator

        members_qs = TeamMember.objects.filter(team=team).select_related("user").order_by("-created_at")

        # Search filter
        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            members_qs = members_qs.filter(
                Q(username__icontains=search)
                | Q(user__email__icontains=search)
            )

        # Enrolled filter
        enrolled = request.query_params.get("enrolled")
        if enrolled == "yes":
            members_qs = members_qs.filter(status=True)
        elif enrolled == "no":
            members_qs = members_qs.filter(status=False)

        total_in_list = members_qs.count()
        all_team_members = TeamMember.objects.filter(team=team)
        enrolled_count = all_team_members.filter(status=True).count()
        not_enrolled_count = all_team_members.filter(status=False).count()
        max_members = team.max_members or 0
        slots_remaining = max(0, max_members - all_team_members.count())

        plan_stats = {
            "max_members": max_members,
            "total_in_list": total_in_list,
            "enrolled_count": enrolled_count,
            "not_enrolled_count": not_enrolled_count,
            "slots_remaining": slots_remaining,
        }

        # Pagination (default 10 per page as in PDF)
        page_number = request.query_params.get("page", 1)
        page_size = request.query_params.get("page_size", 10)
        paginator = Paginator(members_qs, page_size)
        page_obj = paginator.get_page(page_number)

        serializer = TeamMemberItemSerializer(page_obj.object_list, many=True)
        return Response(
            {
                "success": True,
                "plan_stats": plan_stats,
                "pagination": {
                    "current_page": page_obj.number,
                    "total_pages": paginator.num_pages,
                    "total_count": paginator.count,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                },
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        """Batch Add/Edit users from list"""
        team = get_team_for_user(request.user)
        if not team:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamMemberBatchAddSerializer
        from account.models import User, TeamMember
        from core.constants import UserType, CurrentPlanType
        from team_dashboard.utils import generate_secure_password

        serializer = TeamMemberBatchAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        users_data = serializer.validated_data["users"]
        current_count = TeamMember.objects.filter(team=team).count()
        max_members = team.max_members or 0

        added_count = 0
        updated_count = 0

        for item in users_data:
            name = item["name"].strip()
            email = item["email"].strip().lower()

            user_obj = User.objects.filter(email__iexact=email).first()
            if not user_obj:
                user_obj = User.objects.create(
                    email=email,
                    user_type=UserType.MAIN_USER,
                    is_active=True,
                )
                user_obj.set_password(generate_secure_password(16))
                user_obj.save()

            member_obj, created = TeamMember.objects.get_or_create(
                team=team,
                user=user_obj,
                defaults={"username": name, "status": False},
            )

            if created:
                added_count += 1
            else:
                member_obj.username = name
                member_obj.save(update_fields=["username"])
                updated_count += 1

        return Response(
            {
                "success": True,
                "message": f"Successfully processed {len(users_data)} users ({added_count} added, {updated_count} updated).",
                "added_count": added_count,
                "updated_count": updated_count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Import Team Members from CSV File",
    description="Upload a CSV file containing Name and Email columns to bulk add drivers to the team.",
)
class TeamUsersImportCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def post(self, request):
        team = get_team_for_user(request.user)
        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"detail": "Please upload a CSV file with key 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        import csv
        import io
        from account.models import User, TeamMember
        from core.constants import UserType, CurrentPlanType
        from team_dashboard.utils import generate_secure_password

        try:
            decoded_file = csv_file.read().decode("utf-8-sig")
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
        except Exception as e:
            return Response({"detail": f"Error parsing CSV file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        added = 0
        updated = 0
        errors = []

        for row_idx, row in enumerate(reader, start=1):
            # Normalize keys
            clean_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            name = clean_row.get("name") or clean_row.get("full_name") or clean_row.get("user") or ""
            email = clean_row.get("email") or clean_row.get("email_address") or ""

            if not email or "@" not in email:
                errors.append(f"Row {row_idx}: Invalid or missing email.")
                continue

            email = email.lower()
            name = name or email.split("@")[0]

            user_obj = User.objects.filter(email__iexact=email).first()
            if not user_obj:
                user_obj = User.objects.create(
                    email=email,
                    user_type=UserType.MAIN_USER,
                    is_active=True,
                )
                user_obj.set_password(generate_secure_password(16))
                user_obj.save()

            member_obj, created = TeamMember.objects.get_or_create(
                team=team,
                user=user_obj,
                defaults={"username": name, "status": False},
            )
            if created:
                added += 1
            else:
                member_obj.username = name
                member_obj.save(update_fields=["username"])
                updated += 1

        return Response(
            {
                "success": True,
                "message": f"CSV import complete. {added} added, {updated} updated.",
                "added_count": added,
                "updated_count": updated,
                "errors": errors,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Download Team Users as CSV",
    description="Generates and downloads a CSV export of all team members.",
)
class TeamUsersDownloadCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def get(self, request):
        from django.http import HttpResponse
        import csv
        team = get_team_for_user(request.user)
        from account.models import TeamMember

        members = TeamMember.objects.filter(team=team).select_related("user").order_by("username")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="team_users.csv"'

        writer = csv.writer(response)
        writer.writerow(["Name", "Email", "Enrolled", "Joined Date"])

        for m in members:
            name = m.username or m.user.email.split("@")[0]
            enrolled = "Yes" if m.status else "No"
            joined = m.joined_at.strftime("%Y-%m-%d") if m.joined_at else ""
            writer.writerow([name, m.user.email, enrolled, joined])

        return response


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Bulk Remove Team Members",
    description="Removes selected drivers from the team, revoking app access.",
    request=TeamMemberBulkRemoveSerializer,
    responses={200: OpenApiResponse(description="Team members removed.")},
)
class TeamUsersBulkRemoveView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def post(self, request):
        team = get_team_for_user(request.user)
        serializer = TeamMemberBulkRemoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member_ids = serializer.validated_data["member_ids"]
        from account.models import TeamMember

        deleted_count, _ = TeamMember.objects.filter(id__in=member_ids, team=team).delete()

        return Response(
            {
                "success": True,
                "message": f"Successfully removed {deleted_count} team members.",
                "removed_count": deleted_count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Update Team Member Details",
    description="Edits a team member's display name or email address.",
)
class TeamUserDetailView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def patch(self, request, member_id):
        team = get_team_for_user(request.user)
        from account.models import TeamMember
        from team_dashboard.serializers import TeamMemberUpdateSerializer, TeamMemberItemSerializer

        member = TeamMember.objects.filter(id=member_id, team=team).select_related("user").first()
        if not member:
            return Response({"detail": "Team member not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamMemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data.get("name")
        email = serializer.validated_data.get("email")

        if name is not None:
            member.username = name
            member.save(update_fields=["username"])

        if email is not None and email.lower() != member.user.email.lower():
            email = email.lower()
            if User.objects.filter(email__iexact=email).exclude(id=member.user.id).exists():
                return Response({"detail": "This email address is already in use."}, status=status.HTTP_400_BAD_REQUEST)
            member.user.email = email
            member.user.username = email
            member.user.save(update_fields=["email", "username"])

        return Response(TeamMemberItemSerializer(member).data, status=status.HTTP_200_OK)


# =====================================================================
# 4. MANAGE — ROUTE HISTORY VIEWS
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="List Route History with Sequence Numbers",
    description=(
        "Lists routes for this team. Admins with `manage.route_history.team` can view all drivers' routes or filter by `user_id`. "
        "Users with `manage.route_history.my` see their own routes."
    ),
    responses={200: RouteHistoryItemSerializer(many=True)},
)
class TeamRouteHistoryListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = ["manage.route_history.team", "manage.route_history.my"]

    def get(self, request):
        team = get_team_for_user(request.user)
        from team_dashboard.permissions import is_team_super_admin, get_user_team_permissions
        from route.models import Route
        from django.db.models import Q
        from django.core.paginator import Paginator

        user_perms = get_user_team_permissions(request.user)
        can_view_all = is_team_super_admin(request.user) or ("manage.route_history.team" in user_perms)

        # Base query for routes: belongs to team or created by team members
        if team:
            team_driver_ids = list(team.members.values_list("user_id", flat=True)) + [team.owner_id]
            routes_qs = Route.objects.filter(
                Q(team=team) | Q(created_by_id__in=team_driver_ids)
            ).select_related("created_by").order_by("-created_at")
        else:
            routes_qs = Route.objects.filter(created_by=request.user).select_related("created_by").order_by("-created_at")

        driver_user_id = request.query_params.get("user_id")
        if not can_view_all:
            # Force to only current user's routes
            routes_qs = routes_qs.filter(created_by=request.user)
        elif driver_user_id:
            routes_qs = routes_qs.filter(created_by_id=driver_user_id)

        # Search filter
        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            routes_qs = routes_qs.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(created_by__email__icontains=search)
            )

        # Pagination (10 per page)
        page_number = request.query_params.get("page", 1)
        page_size = request.query_params.get("page_size", 10)
        paginator = Paginator(routes_qs, page_size)
        page_obj = paginator.get_page(page_number)

        # Compute sequential #010, #009 based on total count
        total_count = paginator.count
        start_seq = total_count - ((page_obj.number - 1) * int(page_size))
        route_items = []
        for idx, r in enumerate(page_obj.object_list):
            r._route_sequence_number = max(1, start_seq - idx)
            route_items.append(r)

        serializer = RouteHistoryItemSerializer(route_items, many=True)
        return Response(
            {
                "success": True,
                "pagination": {
                    "current_page": page_obj.number,
                    "total_pages": paginator.num_pages,
                    "total_count": paginator.count,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                },
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="Get Waypoints List for a Specific Route",
    description="Returns the waypoint stops and checkpoints for the right panel detail view.",
    responses={200: RouteWaypointItemSerializer(many=True)},
)
class TeamRouteWaypointsView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = ["manage.route_history.team", "manage.route_history.my"]

    def get(self, request, route_id):
        team = get_team_for_user(request.user)
        from route.models import Route, PermitWaypoint

        route = Route.objects.filter(id=route_id).first()
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        waypoints = PermitWaypoint.objects.filter(
            Q(route=route) | Q(permit__route=route)
        ).distinct().order_by("index", "id")

        serializer = RouteWaypointItemSerializer(waypoints, many=True)
        return Response(
            {
                "success": True,
                "route_id": route.id,
                "route_name": route.name,
                "total_waypoints": waypoints.count(),
                "waypoints": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="Bulk Delete Routes",
    description="Deletes selected routes from history.",
    request=RouteHistoryBulkDeleteSerializer,
    responses={200: OpenApiResponse(description="Selected routes deleted.")},
)
class TeamRouteHistoryBulkDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = ["manage.route_history.team", "manage.route_history.my"]

    def post(self, request):
        team = get_team_for_user(request.user)
        from team_dashboard.permissions import is_team_super_admin, get_user_team_permissions
        from route.models import Route
        from team_dashboard.serializers import RouteHistoryBulkDeleteSerializer

        serializer = RouteHistoryBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        route_ids = serializer.validated_data["route_ids"]

        can_view_all = is_team_super_admin(request.user) or ("manage.route_history.team" in get_user_team_permissions(request.user))

        routes = Route.objects.filter(id__in=route_ids)
        if not can_view_all:
            routes = routes.filter(created_by=request.user)
        elif team:
            team_driver_ids = list(team.members.values_list("user_id", flat=True)) + [team.owner_id]
            routes = routes.filter(Q(team=team) | Q(created_by_id__in=team_driver_ids))

        deleted_count, _ = routes.delete()

        return Response(
            {
                "success": True,
                "message": f"Successfully deleted {deleted_count} routes.",
                "deleted_count": deleted_count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="Download Route History as CSV",
    description="Generates a downloadable CSV of route history records.",
)
class TeamRouteHistoryDownloadCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = ["manage.route_history.team", "manage.route_history.my"]

    def get(self, request):
        from django.http import HttpResponse
        import csv
        team = get_team_for_user(request.user)
        from team_dashboard.permissions import is_team_super_admin, get_user_team_permissions
        from route.models import Route
        from django.db.models import Q

        can_view_all = is_team_super_admin(request.user) or ("manage.route_history.team" in get_user_team_permissions(request.user))

        if team:
            team_driver_ids = list(team.members.values_list("user_id", flat=True)) + [team.owner_id]
            routes = Route.objects.filter(
                Q(team=team) | Q(created_by_id__in=team_driver_ids)
            ).select_related("created_by").order_by("-created_at")
        else:
            routes = Route.objects.filter(created_by=request.user).select_related("created_by").order_by("-created_at")

        if not can_view_all:
            routes = routes.filter(created_by=request.user)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="team_route_history.csv"'

        writer = csv.writer(response)
        writer.writerow(["Route #", "Date Created", "Route Name", "Driver Name", "Driver Email", "Distance (km)", "Total Waypoints", "Status"])

        total = routes.count()
        for idx, r in enumerate(routes):
            route_num = f"#{total - idx:03d}"
            date_str = r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
            driver_name = r.created_by.email.split("@")[0]
            writer.writerow([
                route_num,
                date_str,
                r.name or "Untitled Route",
                driver_name,
                r.created_by.email,
                f"{r.total_distance_km:.1f}",
                r.total_waypoints,
                r.status,
            ])

        return response


# =====================================================================
# 5. MANAGE — PLAN VIEW
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Manage Plan"],
    summary="Get Team Plan Details",
    description="Returns read-only plan details, billing frequency, renewal date, and quota stats.",
    responses={200: TeamPlanDetailSerializer},
)
class TeamPlanView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.plan"

    def get(self, request):
        team = get_team_for_user(request.user)
        if not team:
            return Response({"detail": "No active team found."}, status=status.HTTP_404_NOT_FOUND)

        from account.models import TeamMember
        from subscription.models import UserSubscription

        sub = UserSubscription.objects.filter(user=team.owner).order_by("-created_at").first()

        plan_name = "Team Plan"
        billing_freq = "Monthly"
        renewal_date = None

        if sub:
            if sub.plan:
                plan_name = sub.plan.name
            if hasattr(sub, "billing_cycle") and sub.billing_cycle:
                billing_freq = sub.billing_cycle.capitalize()
            if hasattr(sub, "end_date") and sub.end_date:
                renewal_date = sub.end_date.strftime("%B %d, %Y")

        members = TeamMember.objects.filter(team=team)
        enrolled_count = members.filter(status=True).count()
        registered_count = members.count()
        max_users = team.max_members or 0
        slots_remaining = max(0, max_users - registered_count)

        data = {
            "team_name": team.name,
            "owner_email": team.owner.email,
            "plan_name": plan_name,
            "billing_frequency": billing_freq,
            "renewal_date": renewal_date,
            "max_users_allowed": max_users,
            "total_enrolled_users": enrolled_count,
            "total_registered_users": registered_count,
            "slots_remaining": slots_remaining,
            "is_active": team.is_active,
        }
        return Response(data, status=status.HTTP_200_OK)


# =====================================================================
# 6. PERMISSIONS TREE VIEW (UTILITY)
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Manage"],
    summary="Get Permissions Tree for UI Checkboxes",
    description="Returns the full hierarchical permissions tree for rendering checkboxes on Add/Edit Admin User form.",
)
class TeamPermissionTreeView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser]

    def get(self, request):
        from team_dashboard.constants import TEAM_PERMISSION_TREE, TEAM_DASHBOARD_PERMISSIONS
        return Response(
            {
                "permission_tree": TEAM_PERMISSION_TREE,
                "all_permissions": TEAM_DASHBOARD_PERMISSIONS,
            },
            status=status.HTTP_200_OK,
        )

