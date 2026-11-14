import logging
import re

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiTypes
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower

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
    is_team_manage_otp_expired,
    mask_email_address,
    queue_team_driver_invitation,
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
    TeamManageOTPResponseSerializer,
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
    TeamMemberBulkInviteSerializer,
    TeamUsersStatsSerializer,
    # Manage — Route History
    RouteHistoryItemSerializer,
    RouteWaypointItemSerializer,
    RouteHistoryBulkDeleteSerializer,
    TeamRouteCreateRequestSerializer,
    TeamRouteUpdateRequestSerializer,
    TeamRoutePermitWriteSerializer,
    TeamRouteWaypointWriteSerializer,
    TeamRouteMapUpdateRequestSerializer,
    TeamRouteMutationResponseSerializer,
    TeamRoutePermitMutationResponseSerializer,
    TeamRouteWaypointMutationResponseSerializer,
    TeamPermitParseRequestSerializer,
    TeamPermitParseResponseSerializer,
    # Manage — Plan
    TeamPlanDetailSerializer,
    TeamUsersListResponseSerializer,
    TeamUsersProcessResponseSerializer,
    TeamUsersInviteFailureResponseSerializer,
    TeamUsersInviteSummarySerializer,
    TeamUsersImportResponseSerializer,
    TeamUsersImportCSVRequestSerializer,
    TeamAdminGeneratePasswordResponseSerializer,
    TeamPermissionTreeResponseSerializer,
)
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS

logger = logging.getLogger(__name__)



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
                "expires_in_seconds": 900,
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
                "expires_in_seconds": 900,
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
    summary="Send or Resend Verification Code for Email/Password Change",
    description=(
        "Sends a 6-digit OTP to the current logged-in user's email. Calling this endpoint "
        "again resends a fresh code, invalidates every previous unused manage code, and restarts "
        "the 10-minute expiry window."
    ),
    request=TeamSendManageOTPRequestSerializer,
    responses={200: TeamManageOTPResponseSerializer},
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
                "action": action,
                "expires_in_seconds": 600,
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

        if not otp_obj or is_team_manage_otp_expired(otp_obj):
            return Response(
                {"success": False, "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # User has no `username` field; email is the configured login identity.
        # Keep the email update and OTP consumption atomic so a failed update
        # does not consume the verification code.
        with transaction.atomic():
            user.email = new_email
            user.save(update_fields=["email", "updated_at"])

            otp_obj.is_verified = True
            otp_obj.verified_at = timezone.now()
            otp_obj.save(update_fields=["is_verified", "verified_at"])

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

        if not otp_obj or is_team_manage_otp_expired(otp_obj):
            return Response(
                {"success": False, "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user.set_password(new_password)
            user.save(update_fields=["password", "updated_at"])

            otp_obj.is_verified = True
            otp_obj.verified_at = timezone.now()
            otp_obj.save(update_fields=["is_verified", "verified_at"])

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

    @extend_schema(responses={200: TeamAdminUserListSerializer(many=True)})
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

    @extend_schema(request=TeamAdminUserCreateSerializer, responses={201: TeamAdminUserDetailSerializer})
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
    serializer_class = TeamAdminUserDetailSerializer
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.admin_users"

    def get_profile(self, request, user_id):
        team = get_team_for_user(request.user)
        from team_dashboard.models import TeamAdminProfile
        return TeamAdminProfile.objects.filter(user_id=user_id, team=team).select_related("user", "team").first()

    @extend_schema(responses={200: TeamAdminUserDetailSerializer})
    def get(self, request, user_id):
        profile = self.get_profile(request, user_id)
        if not profile:
            return Response({"detail": "Admin user not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamAdminUserDetailSerializer
        return Response(TeamAdminUserDetailSerializer(profile).data, status=status.HTTP_200_OK)

    @extend_schema(request=TeamAdminUserUpdateSerializer, responses={200: TeamAdminUserDetailSerializer})
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
            if not is_active:
                from account.models import OTPVerification
                from core.constants import OTPPurpose
                OTPVerification.objects.filter(
                    user=profile.user,
                    purpose=OTPPurpose.LOGIN,
                    is_verified=False,
                ).delete()

        if password:
            profile.user.set_password(password)
            profile.user.save(update_fields=["password"])

        profile.updated_by = request.user
        profile.save()

        return Response(TeamAdminUserDetailSerializer(profile).data, status=status.HTTP_200_OK)

    @extend_schema(responses={200: OpenApiResponse(description="Admin user deleted successfully.")})
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

        # Prevent an OTP requested before lockout from completing login.
        from account.models import OTPVerification
        from core.constants import OTPPurpose
        OTPVerification.objects.filter(
            user=profile.user,
            purpose=OTPPurpose.LOGIN,
            is_verified=False,
        ).delete()

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
            locked_user_ids = list(profiles.values_list("user_id", flat=True))
            count = profiles.update(is_active=False)
            from account.models import OTPVerification
            from core.constants import OTPPurpose
            OTPVerification.objects.filter(
                user_id__in=locked_user_ids,
                purpose=OTPPurpose.LOGIN,
                is_verified=False,
            ).delete()
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
    responses={200: TeamAdminGeneratePasswordResponseSerializer},
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

def _normalize_csv_header(value):
    """Normalize Excel/CSV headers such as 'First Name', 'first_name', or BOM-prefixed names."""
    normalized = str(value or "").lstrip("\ufeff").strip().casefold()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _team_member_values_from_csv_row(row):
    clean_row = {
        _normalize_csv_header(key): str(value or "").strip()
        for key, value in row.items()
        if key
    }
    email = (
        clean_row.get("email")
        or clean_row.get("email_address")
        or clean_row.get("e_mail")
        or ""
    )
    name = (
        clean_row.get("name")
        or clean_row.get("full_name")
        or clean_row.get("driver_name")
        or clean_row.get("user")
        or ""
    )
    if not name:
        name = " ".join(
            part
            for part in (
                clean_row.get("first_name", ""),
                clean_row.get("last_name", ""),
            )
            if part
        ).strip()
    return name, email


def _create_or_update_team_member(team, name, email):
    """Create or update a driver without implicitly sending an invitation."""
    from account.models import TeamMember, User
    from core.constants import UserType
    from team_dashboard.utils import generate_secure_password

    with transaction.atomic():
        user_obj = User.objects.filter(email__iexact=email).first()
        if not user_obj:
            user_obj = User.objects.create(
                email=email,
                user_type=UserType.MAIN_USER,
                is_active=True,
            )
            user_obj.set_password(generate_secure_password(16))
            user_obj.save(update_fields=["password", "updated_at"])

        member_obj, created = TeamMember.objects.get_or_create(
            team=team,
            user=user_obj,
            defaults={"username": name, "status": False},
        )
        if not created:
            member_obj.username = name
            member_obj.save(update_fields=["username", "updated_at"])
        return member_obj, created


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="List or batch add Team Members",
    description="GET lists team drivers/members with plan slot statistics. POST batch-adds/updates users from the editable list.",
)
class TeamUsersListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, description="Search by name or email."),
            OpenApiParameter("q", OpenApiTypes.STR, description="Alias for search."),
            OpenApiParameter("enrolled", OpenApiTypes.STR, enum=["yes", "no"], description="Filter enrolled status."),
            OpenApiParameter("page", OpenApiTypes.INT, description="Page number."),
            OpenApiParameter("page_size", OpenApiTypes.INT, description="Page size."),
            OpenApiParameter("ordering", OpenApiTypes.STR, enum=["first_name"], description="Sort alphabetically by first name before pagination."),
        ],
        responses={200: TeamUsersListResponseSerializer},
    )
    def get(self, request):
        team = get_team_for_user(request.user)
        if not team:
            return Response(
                {
                    "success": True,
                    "results": [],
                    "pagination": {
                        "current_page": 1,
                        "total_pages": 0,
                        "total_count": 0,
                        "has_next": False,
                        "has_previous": False,
                    },
                    "plan_stats": {
                        "max_members": 0,
                        "total_in_list": 0,
                        "enrolled_count": 0,
                        "not_enrolled_count": 0,
                        "slots_remaining": 0,
                    },
                },
                status=status.HTTP_200_OK,
            )

        from account.models import TeamMember
        from django.db.models import Q
        from team_dashboard.serializers import TeamMemberItemSerializer, TeamUsersStatsSerializer
        from django.core.paginator import Paginator

        members_qs = TeamMember.objects.filter(team=team).select_related("user")

        # Search filter
        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            members_qs = members_qs.filter(
                Q(username__icontains=search)
                | Q(user__email__icontains=search)
            )

        # Enrolled filter
        enrolled = (request.query_params.get("enrolled") or "").strip().casefold()
        if enrolled == "yes":
            members_qs = members_qs.filter(status=True)
        elif enrolled == "no":
            members_qs = members_qs.filter(status=False)

        ordering = (request.query_params.get("ordering") or "").strip()
        if ordering and ordering != "first_name":
            return Response(
                {"detail": "Supported ordering value is 'first_name'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ordering == "first_name":
            members_qs = members_qs.order_by(Lower("username"), Lower("user__email"), "id")
        else:
            members_qs = members_qs.order_by("-created_at", "id")

        total_in_list = members_qs.count()
        all_team_members = TeamMember.objects.filter(team=team)
        enrolled_count = all_team_members.filter(status=True).count()
        not_enrolled_count = all_team_members.filter(status=False).count()
        from subscription.services.validators import TeamMemberValidator
        max_members = TeamMemberValidator.sync_team_max_members(team)

        slots_remaining = max(0, max_members - all_team_members.count())

        plan_stats = {
            "max_members": max_members,
            "total_in_list": total_in_list,
            "enrolled_count": enrolled_count,
            "not_enrolled_count": not_enrolled_count,
            "slots_remaining": slots_remaining,
        }

        # Pagination (default 10 per page as in PDF)
        try:
            page_number = max(1, int(request.query_params.get("page", 1)))
            page_size = int(request.query_params.get("page_size", 10))
        except (TypeError, ValueError):
            return Response({"detail": "page and page_size must be integers."}, status=status.HTTP_400_BAD_REQUEST)
        if not 1 <= page_size <= 1000:
            return Response({"detail": "page_size must be between 1 and 1000."}, status=status.HTTP_400_BAD_REQUEST)
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

    @extend_schema(
        request=TeamMemberBatchAddSerializer,
        responses={
            200: TeamUsersProcessResponseSerializer,
            409: OpenApiResponse(description="Plan capacity exceeded or a concurrent duplicate was added."),
        },
    )
    def post(self, request):
        """Batch Add/Edit users from list"""
        team = get_team_for_user(request.user)
        if not team:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)

        from team_dashboard.serializers import TeamMemberBatchAddSerializer
        from account.models import TeamMember

        serializer = TeamMemberBatchAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        users_data = serializer.validated_data["users"]
        normalized_rows = [
            {"name": item["name"].strip(), "email": item["email"].strip().lower()}
            for item in users_data
        ]
        empty_names = [index + 1 for index, item in enumerate(normalized_rows) if not item["name"]]
        if empty_names:
            return Response(
                {"detail": "Name cannot be blank.", "rows": empty_names},
                status=status.HTTP_400_BAD_REQUEST,
            )

        emails = [item["email"] for item in normalized_rows]
        email_query = Q()
        for email in emails:
            email_query |= Q(user__email__iexact=email)
        duplicates = list(
            TeamMember.objects.filter(email_query, team=team)
            .values_list("user__email", flat=True)
        )
        if duplicates:
            return Response(
                {"detail": "One or more emails are already on this team.", "duplicate_emails": sorted(duplicates)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from subscription.services.validators import TeamMemberValidator
        max_members = TeamMemberValidator.sync_team_max_members(team)
        try:
            with transaction.atomic():
                team.__class__.objects.select_for_update().get(pk=team.pk)
                current_count = TeamMember.objects.filter(team=team).count()
                if current_count + len(normalized_rows) > max_members:
                    return Response(
                        {
                            "detail": "Adding these users would exceed the team plan capacity.",
                            "max_members": max_members,
                            "current_count": current_count,
                            "requested_count": len(normalized_rows),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                concurrent_duplicates = list(
                    TeamMember.objects.filter(email_query, team=team)
                    .values_list("user__email", flat=True)
                )
                if concurrent_duplicates:
                    return Response(
                        {
                            "detail": "One or more emails are already on this team.",
                            "duplicate_emails": sorted(concurrent_duplicates),
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                for item in normalized_rows:
                    _create_or_update_team_member(team, item["name"], item["email"])
        except IntegrityError:
            return Response(
                {"detail": "A user with one of these emails was added concurrently. Refresh and retry."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "success": True,
                "message": f"Successfully added {len(normalized_rows)} users.",
                "added_count": len(normalized_rows),
                "updated_count": 0,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Import Team Members from CSV File",
    description="Upload multipart/form-data with file=<csv>. CSV should contain Name and Email columns.",
    request=TeamUsersImportCSVRequestSerializer,
    responses={200: TeamUsersImportResponseSerializer},
)
class TeamUsersImportCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [MultiPartParser, FormParser]
    required_team_permission = "manage.team_users"

    def post(self, request):
        team = get_team_for_user(request.user)
        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"detail": "Please upload a CSV file with key 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        import csv
        import io
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
            name, email = _team_member_values_from_csv_row(row)

            if not email or "@" not in email:
                errors.append(f"Row {row_idx}: Invalid or missing email.")
                continue

            email = email.lower()
            name = name or email.split("@")[0]

            try:
                _member_obj, created = _create_or_update_team_member(team, name, email)
            except Exception:
                logger.exception("Unable to import team driver on CSV row %s", row_idx)
                errors.append(f"Row {row_idx}: The user could not be added.")
                continue
            added += int(created)
            updated += int(not created)

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
    description="Returns all team users as a text/csv attachment.",
    responses={200: OpenApiResponse(response=OpenApiTypes.BINARY, description="CSV file download (text/csv).")},
)
class TeamUsersDownloadCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def get(self, request):
        from django.http import HttpResponse
        import csv
        team = get_team_for_user(request.user)
        from account.models import TeamMember

        members = (
            TeamMember.objects.filter(team=team)
            .select_related("user")
            .order_by(Lower("username"), Lower("user__email"), "id")
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="team_users_export.csv"'

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

        members = TeamMember.objects.filter(id__in=member_ids, team=team)
        if members.count() != len(member_ids):
            return Response(
                {"detail": "One or more team members were not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        deleted_count, _ = members.delete()

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
    summary="Queue invitations for selected team members",
    description="Owner-only, durable, idempotent invitation queueing for selected unenrolled drivers.",
    request=TeamMemberBulkInviteSerializer,
    responses={
        200: TeamUsersInviteSummarySerializer,
        400: OpenApiResponse(description="Invalid or incomplete member ID list."),
        403: OpenApiResponse(description="The requester is not the owner or a member belongs to another team."),
        404: OpenApiResponse(description="No matching members exist."),
        409: OpenApiResponse(description="A selected member is already enrolled."),
        503: OpenApiResponse(description="The durable invitation queue is unavailable."),
    },
)
class TeamUsersSendInviteView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.team_users"

    def post(self, request):
        team = get_team_for_user(request.user)
        if not team:
            return Response({"detail": "Team not found."}, status=status.HTTP_404_NOT_FOUND)
        if team.owner_id != request.user.id:
            return Response(
                {"detail": "Only the team owner can send driver invitations."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TeamMemberBulkInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member_ids = serializer.validated_data["member_ids"]

        from account.models import TeamMember

        found_members = list(
            TeamMember.objects.filter(id__in=member_ids)
            .select_related("team", "user")
            .order_by("id")
        )
        if not found_members:
            return Response({"detail": "No matching team members found."}, status=status.HTTP_404_NOT_FOUND)

        foreign_ids = [member.id for member in found_members if member.team_id != team.id]
        if foreign_ids:
            return Response(
                {"detail": "One or more selected members do not belong to your team."},
                status=status.HTTP_403_FORBIDDEN,
            )

        found_ids = {member.id for member in found_members}
        missing_ids = [member_id for member_id in member_ids if member_id not in found_ids]
        if missing_ids:
            return Response(
                {"detail": "One or more member IDs do not exist.", "missing_member_ids": missing_ids},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrolled_ids = [member.id for member in found_members if member.status]
        if enrolled_ids:
            return Response(
                {"detail": "Enrolled members cannot be invited again.", "member_ids": enrolled_ids},
                status=status.HTTP_409_CONFLICT,
            )

        queued_count = 0
        idempotent_count = 0
        try:
            with transaction.atomic():
                for member in found_members:
                    _invite, newly_queued = queue_team_driver_invitation(team, member)
                    queued_count += int(newly_queued)
                    idempotent_count += int(not newly_queued)
        except DatabaseError:
            logger.exception("The team invitation queue is unavailable for team %s", team.pk)
            return Response(
                {"detail": "The invitation queue is temporarily unavailable. Please retry."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        message = f"{queued_count} invitation{'s' if queued_count != 1 else ''} queued"
        if idempotent_count:
            message += f"; {idempotent_count} already pending"
        return Response(
            {
                "message": message,
                "queued_count": queued_count,
                "failed_count": 0,
                "failures": [],
                "idempotent_count": idempotent_count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Manage Team Users"],
    summary="Update Team Member Details",
    description="Edits a team member's display name or email address.",
    request=TeamMemberUpdateSerializer,
    responses={200: TeamMemberItemSerializer},
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

        normalized_email = email.lower() if email is not None else None
        if normalized_email is not None and normalized_email != member.user.email.lower():
            from account.models import User
            if User.objects.filter(email__iexact=normalized_email).exclude(id=member.user.id).exists():
                return Response({"detail": "This email address is already in use."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if name is not None:
                member.username = name.strip()
                member.save(update_fields=["username", "updated_at"])
            if normalized_email is not None and normalized_email != member.user.email.lower():
                member.user.email = normalized_email
                member.user.save(update_fields=["email", "updated_at"])

        return Response(TeamMemberItemSerializer(member).data, status=status.HTTP_200_OK)


# =====================================================================
# 4. MANAGE — ROUTE HISTORY VIEWS
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="List Route History with Sequence Numbers",
    description=(
        "Lists routes for this team. Team owners/admins/managers with `manage.route_history.team` can view all drivers' routes or filter by `user_id` or `user_email`."
    ),
    parameters=[
        OpenApiParameter("user_id", OpenApiTypes.INT, description="Filter by team driver user ID."),
        OpenApiParameter("user_email", OpenApiTypes.EMAIL, description="Filter by team driver email."),
        OpenApiParameter("search", OpenApiTypes.STR, description="Search route name, description, or driver email."),
    ],
    responses={200: RouteHistoryItemSerializer(many=True)},
)
class TeamRouteHistoryListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def get(self, request):
        team = get_team_for_user(request.user)
        from route.models import Route
        from django.db.models import Q
        # Team is the authorization boundary; user is the selected driver.
        if team:
            routes_qs = (
                Route.objects.filter(team=team)
                .select_related("user", "created_by")
                .order_by("-created_at")
            )
        else:
            routes_qs = Route.objects.none()

        driver_user_id = request.query_params.get("user_id")
        if driver_user_id:
            routes_qs = routes_qs.filter(user_id=driver_user_id)

        driver_email = request.query_params.get("user_email")
        if driver_email:
            routes_qs = routes_qs.filter(user__email__iexact=driver_email.strip())

        # Search filter
        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            routes_qs = routes_qs.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(user__email__icontains=search)
            )

        # This endpoint's published contract is a JSON array.
        route_items = list(routes_qs)
        start_seq = len(route_items)
        for idx, r in enumerate(route_items):
            r._route_sequence_number = max(1, start_seq - idx)

        serializer = RouteHistoryItemSerializer(route_items, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Route History"],
    summary="Get Waypoints List for a Specific Route",
    description="Returns the waypoint stops and checkpoints for the right panel detail view.",
    responses={200: RouteWaypointItemSerializer(many=True)},
)
class TeamRouteWaypointsView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def get(self, request, route_id):
        from route.models import PermitWaypoint

        route = _get_team_route_or_404(request, route_id)
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
    required_team_permission = "manage.route_history.team"

    def post(self, request):
        team = get_team_for_user(request.user)
        from route.models import Route
        from team_dashboard.serializers import RouteHistoryBulkDeleteSerializer

        serializer = RouteHistoryBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        route_ids = serializer.validated_data["route_ids"]

        routes = Route.objects.filter(id__in=route_ids)
        if team:
            routes = routes.filter(team=team)
        else:
            routes = Route.objects.none()

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
    description="Returns text/csv attachment with Content-Disposition filename=team_route_history.csv.",
    responses={200: OpenApiResponse(response=OpenApiTypes.BINARY, description="CSV file download (text/csv).")},
)
class TeamRouteHistoryDownloadCSVView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def get(self, request):
        from django.http import HttpResponse
        import csv
        team = get_team_for_user(request.user)
        from route.models import Route
        from django.db.models import Q


        if team:
            routes = (
                Route.objects.filter(team=team)
                .select_related("user", "created_by")
                .order_by("-created_at")
            )
        else:
            routes = Route.objects.none()

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="team_route_history.csv"'

        writer = csv.writer(response)
        writer.writerow(["Route #", "Date Created", "Route Name", "Driver Name", "Driver Email", "Distance (km)", "Total Waypoints", "Status"])

        total = routes.count()
        for idx, r in enumerate(routes):
            route_num = f"#{total - idx:03d}"
            date_str = r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
            driver_name = r.user.email.split("@")[0]
            writer.writerow([
                route_num,
                date_str,
                r.name or "Untitled Route",
                driver_name,
                r.user.email,
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
        from subscription.services.validators import TeamMemberValidator
        max_users = TeamMemberValidator.sync_team_max_members(team)
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
    responses={200: TeamPermissionTreeResponseSerializer},
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




# =====================================================================
# TEAM DASHBOARD ROUTE MANAGEMENT HELPERS / VIEWS
# =====================================================================

@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Parse a permit into state-bounded route points",
    description=(
        "Accepts one PDF/image file or raw permit_text. OCR-extracted locations are "
        "geocoded only within the detected issuing state (or state_hint). Unresolved "
        "locations are reported instead of being placed in another state."
    ),
    request=TeamPermitParseRequestSerializer,
    responses={200: TeamPermitParseResponseSerializer},
)
class TeamPermitParseView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_team_permission = "manage.route_history.team"

    def post(self, request):
        from route.service import parse_permit_route

        serializer = TeamPermitParseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parsed = parse_permit_route(
            permit_file=serializer.validated_data.get("file"),
            permit_text=serializer.validated_data.get("permit_text"),
            state_hint=serializer.validated_data.get("state_hint"),
        )
        response_serializer = TeamPermitParseResponseSerializer(data=parsed)
        response_serializer.is_valid(raise_exception=True)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

def _team_can_manage_all_routes(user):
    return is_team_super_admin(user) or ("manage.route_history.team" in get_user_team_permissions(user))


def _team_route_queryset(request):
    from route.models import Route

    team = get_team_for_user(request.user)
    if not team:
        return Route.objects.none()

    queryset = (
        Route.objects.filter(team=team)
        .select_related("user", "created_by", "team")
        .prefetch_related("permits", "permits__waypoints")
    )

    return queryset


def _get_team_route_or_404(request, route_id):
    return _team_route_queryset(request).filter(id=route_id).first()


def _get_target_team_driver_or_error(request, user_id):
    from account.models import TeamMember

    team = get_team_for_user(request.user)
    if not team:
        return None, Response({"detail": "Active team not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None, Response({"detail": "Invalid user_id."}, status=status.HTTP_400_BAD_REQUEST)


    membership = (
        TeamMember.objects.select_related("user")
        .filter(team=team, user_id=user_id)
        .first()
    )
    if not membership:
        return None, Response({"detail": "Driver does not belong to this team."}, status=status.HTTP_404_NOT_FOUND)
    if not membership.status or not membership.user.is_active:
        return None, Response(
            {"detail": "Driver is not enrolled and active on this team."},
            status=status.HTTP_409_CONFLICT,
        )

    return membership.user, None


def _sync_route_waypoint_count(route):
    total = route.waypoints.count()
    if total != route.total_waypoints:
        route.total_waypoints = total
        route.save(update_fields=["total_waypoints", "updated_at"])
    return total


def _same_coordinates(lat1, lng1, lat2, lng2, tolerance=0.0001):
    return abs(lat1 - lat2) <= tolerance and abs(lng1 - lng2) <= tolerance


def _validate_permit_against_neighbors(route, payload, permit=None):
    """Prevent gaps between a permit and its adjacent permit segments."""
    from route.models import RoutePermit

    index = payload.get("index") or (permit.index if permit else None)
    if index is None:
        return
    start_lat = payload.get("start_latitude", getattr(permit, "start_latitude", None))
    start_lng = payload.get("start_longitude", getattr(permit, "start_longitude", None))
    end_lat = payload.get("end_latitude", getattr(permit, "end_latitude", None))
    end_lng = payload.get("end_longitude", getattr(permit, "end_longitude", None))

    previous = RoutePermit.objects.filter(route=route, index__lt=index).order_by("-index").first()
    following = RoutePermit.objects.filter(route=route, index__gt=index).order_by("index").first()
    if previous and not _same_coordinates(previous.end_latitude, previous.end_longitude, start_lat, start_lng):
        raise ValidationError({
            "start_latitude": f"Permit {index} start must match Permit {previous.index} end.",
            "start_longitude": f"Permit {index} start must match Permit {previous.index} end.",
        })
    if following and not _same_coordinates(end_lat, end_lng, following.start_latitude, following.start_longitude):
        raise ValidationError({
            "end_latitude": f"Permit {index} end must match Permit {following.index} start.",
            "end_longitude": f"Permit {index} end must match Permit {following.index} start.",
        })


def _shift_waypoint_indexes_for_insert(permit, insertion_index):
    """Create one index slot without violating the (permit, index) unique key."""
    from django.db.models import F

    queryset = permit.waypoints.filter(index__gte=insertion_index)
    queryset.update(index=F("index") + 1000000)
    queryset.update(index=F("index") - 999999)


def _compact_waypoint_indexes(permit):
    """Renumber remaining waypoints to 1..N after a deletion."""
    from django.db.models import F
    from route.models import PermitWaypoint

    waypoints = list(permit.waypoints.order_by("index", "id"))
    permit.waypoints.update(index=F("index") + 1000000)
    for position, waypoint in enumerate(waypoints, start=1):
        waypoint.index = position
    if waypoints:
        PermitWaypoint.objects.bulk_update(waypoints, ["index"])


def _move_waypoint_to_index(permit, waypoint, desired_index):
    """Move one waypoint while preserving a unique, contiguous order."""
    from django.db.models import F
    from route.models import PermitWaypoint

    waypoints = list(permit.waypoints.order_by("index", "id"))
    if desired_index < 1 or desired_index > len(waypoints):
        raise ValidationError({"index": f"Index must be between 1 and {len(waypoints)}."})
    ordered = [item for item in waypoints if item.id != waypoint.id]
    ordered.insert(desired_index - 1, waypoint)
    permit.waypoints.update(index=F("index") + 1000000)
    for position, item in enumerate(ordered, start=1):
        item.index = position
    PermitWaypoint.objects.bulk_update(ordered, ["index"])


def _build_extracted_waypoints(permit, route, permit_file=None, permit_text=None):
    if not (permit_file or permit_text):
        return []

    from route.models import PermitWaypoint
    from route.service import extract_route_data, get_intersection_lat_lng

    route_data = extract_route_data(
        permit_file=permit_file,
        permit_text=permit_text,
        state_hint=permit.issuing_state,
    )
    intersections = (route_data or {}).get("intersection", [])
    start_coords = (permit.start_latitude, permit.start_longitude)
    end_coords = (permit.end_latitude, permit.end_longitude)

    waypoints = (
        get_intersection_lat_lng(
            intersections,
            start_coords=start_coords,
            end_coords=end_coords,
            state_hint=permit.issuing_state,
        )
        if intersections
        else []
    )
    return [
        PermitWaypoint(
            permit=permit,
            route=route,
            index=index,
            name=wp.get("name") or f"Waypoint {index}",
            latitude=wp.get("lat"),
            longitude=wp.get("lng"),
        )
        for index, wp in enumerate(waypoints, start=1)
        if wp.get("lat") is not None and wp.get("lng") is not None
    ]


def _replace_permit_waypoints(permit, route, waypoints_data):
    from route.models import PermitWaypoint

    permit.waypoints.all().delete()
    waypoint_objects = []
    for position, item in enumerate(waypoints_data, start=1):
        waypoint_objects.append(
            PermitWaypoint(
                permit=permit,
                route=route,
                # The array order is authoritative for a full replacement. This
                # guarantees contiguous indexes even if the client sends stale IDs.
                index=position,
                name=item["name"],
                waypoint_type=item.get("waypoint_type") or "CHECKPOINT",
                latitude=item["latitude"],
                longitude=item["longitude"],
                description=item.get("description"),
                icon=item.get("icon") or "pin",
                eta_minutes=item.get("eta_minutes") or 0,
            )
        )
    PermitWaypoint.objects.bulk_create(waypoint_objects)
    _sync_route_waypoint_count(route)


def _create_or_update_permit(route, validated_data, permit=None, replace_waypoints=True):
    from django.db.models import Max
    from route.models import RoutePermit, PermitWaypoint

    waypoints_data = validated_data.pop("waypoints", None)
    permit_file = validated_data.get("permit_file")
    permit_text = validated_data.get("permit_text")

    if permit is None:
        current_max = RoutePermit.objects.filter(route=route).aggregate(Max("index"))["index__max"]
        validated_data["index"] = validated_data.get("index") or ((current_max or 0) + 1)
        validated_data["name"] = validated_data.get("name") or f"Permit {validated_data['index']}"
        permit = RoutePermit.objects.create(route=route, **validated_data)
    else:
        for field, value in validated_data.items():
            setattr(permit, field, value)
        permit.save()

    if waypoints_data is not None:
        if replace_waypoints:
            _replace_permit_waypoints(permit, route, waypoints_data)
    elif permit_file or permit_text:
        permit.waypoints.all().delete()
        PermitWaypoint.objects.bulk_create(
            _build_extracted_waypoints(permit, route, permit_file=permit_file, permit_text=permit_text)
        )
        _sync_route_waypoint_count(route)

    return permit


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Create route for a team driver",
    description="Creates a route on behalf of a team driver. Use the user_id returned by the team users list.",
    request=TeamRouteCreateRequestSerializer,
    responses={201: TeamRouteMutationResponseSerializer},
)
class TeamDriverRouteCreateView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_team_permission = "manage.route_history.team"

    def post(self, request, user_id):
        from django.db import transaction
        from route.models import Route
        from route.serializers import AdminRouteHistoryDetailSerializer

        target_user, error_response = _get_target_team_driver_or_error(request, user_id)
        if error_response is not None:
            return error_response

        serializer = TeamRouteCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        permits_data = data.pop("permits", None)
        team = get_team_for_user(request.user)

        with transaction.atomic():
            name = (data.get("name") or "").strip()
            if not name:
                name = f"{data.get('start_location', '')} to {data.get('end_location', '')}".strip(" to") or "Untitled Route"

            route = Route.objects.create(
                user=target_user,
                created_by=request.user,
                team=team,
                name=name,
                description=data.get("description"),
            )
            if permits_data is not None:
                for position, payload in enumerate(permits_data, start=1):
                    permit_data = dict(payload)
                    permit_data.setdefault("index", position)
                    permit_data.setdefault("name", f"Permit {position}")
                    _create_or_update_permit(route, permit_data)
            else:
                permit_data = {
                    "index": 1,
                    "name": "Permit 1",
                    "start_location": data["start_location"],
                    "start_latitude": data["start_latitude"],
                    "start_longitude": data["start_longitude"],
                    "end_location": data["end_location"],
                    "end_latitude": data["end_latitude"],
                    "end_longitude": data["end_longitude"],
                    "permit_file": data.get("permit_file"),
                    "permit_text": data.get("permit_text"),
                }
                if "waypoints" in data:
                    permit_data["waypoints"] = data["waypoints"]
                _create_or_update_permit(route, permit_data)
            _sync_route_waypoint_count(route)

        detail = AdminRouteHistoryDetailSerializer(route, context={"request": request}).data
        return Response(
            {
                "success": True,
                "message": "Route created successfully.",
                "route_id": route.id,
                "data": detail,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Retrieve or update a team route",
    request=TeamRouteUpdateRequestSerializer,
    responses={200: OpenApiResponse(description="Route detail or updated route response.")},
)
class TeamRouteDetailManageView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def get(self, request, route_id):
        from route.serializers import AdminRouteHistoryDetailSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminRouteHistoryDetailSerializer(route, context={"request": request})
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def patch(self, request, route_id):
        from route.serializers import AdminRouteHistoryDetailSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRouteUpdateRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(route, field, value)
        route.save()

        response_serializer = AdminRouteHistoryDetailSerializer(route, context={"request": request})
        return Response(
            {
                "success": True,
                "message": "Route updated successfully.",
                "route_id": route.id,
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Update route map payload",
    description="Updates route metadata and nested permits/waypoints in one save request from the route edit screen.",
    request=TeamRouteMapUpdateRequestSerializer,
    responses={200: TeamRouteMutationResponseSerializer},
)
class TeamRouteMapUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_team_permission = "manage.route_history.team"

    def patch(self, request, route_id):
        from django.db import transaction
        from route.models import RoutePermit
        from route.serializers import AdminRouteHistoryDetailSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRouteMapUpdateRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        permits_data = data.pop("permits", None)
        delete_missing_permits = data.pop("delete_missing_permits", False)
        replace_waypoints = data.pop("replace_waypoints", True)

        with transaction.atomic():
            for field, value in data.items():
                setattr(route, field, value)
            route.save()

            seen_permit_ids = []
            if permits_data is not None:
                for permit_payload in permits_data:
                    permit_payload = dict(permit_payload)
                    permit_id = permit_payload.pop("id", None)
                    permit = None
                    if permit_id:
                        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
                        if not permit:
                            return Response({"detail": f"Permit {permit_id} not found for this route."}, status=status.HTTP_404_NOT_FOUND)
                    permit = _create_or_update_permit(route, permit_payload, permit=permit, replace_waypoints=replace_waypoints)
                    seen_permit_ids.append(permit.id)

                if delete_missing_permits:
                    RoutePermit.objects.filter(route=route).exclude(id__in=seen_permit_ids).delete()

            _sync_route_waypoint_count(route)

        response_serializer = AdminRouteHistoryDetailSerializer(route, context={"request": request})
        return Response(
            {
                "success": True,
                "message": "Route map updated successfully.",
                "route_id": route.id,
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Add permit to a team route",
    request=TeamRoutePermitWriteSerializer,
    responses={201: TeamRoutePermitMutationResponseSerializer},
)
class TeamRoutePermitListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_team_permission = "manage.route_history.team"

    def post(self, request, route_id):
        from django.db import transaction
        from route.serializers import RoutePermitSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRoutePermitWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            permit_data = dict(serializer.validated_data)
            next_index = (route.permits.order_by("index").last().index + 1) if route.permits.exists() else 1
            requested_index = permit_data.get("index")
            if requested_index is not None and requested_index != next_index:
                raise ValidationError({"index": f"The next permit index must be {next_index}."})
            permit_data["index"] = next_index
            _validate_permit_against_neighbors(route, permit_data)
            permit = _create_or_update_permit(route, permit_data)
        return Response(
            {
                "success": True,
                "message": "Permit added successfully.",
                "permit_id": permit.id,
                "data": RoutePermitSerializer(permit, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Update or delete a permit on a team route",
    request=TeamRoutePermitWriteSerializer,
    responses={200: TeamRoutePermitMutationResponseSerializer},
)
class TeamRoutePermitDetailView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_team_permission = "manage.route_history.team"

    def patch(self, request, route_id, permit_id):
        from django.db import transaction
        from route.models import RoutePermit
        from route.serializers import RoutePermitSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
        if not permit:
            return Response({"detail": "Permit not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRoutePermitWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            permit_data = dict(serializer.validated_data)
            _validate_permit_against_neighbors(route, permit_data, permit=permit)
            permit = _create_or_update_permit(route, permit_data, permit=permit)
        return Response(
            {
                "success": True,
                "message": "Permit updated successfully.",
                "permit_id": permit.id,
                "data": RoutePermitSerializer(permit, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, route_id, permit_id):
        from route.models import RoutePermit

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
        if not permit:
            return Response({"detail": "Permit not found."}, status=status.HTTP_404_NOT_FOUND)
        permit.delete()
        _sync_route_waypoint_count(route)
        return Response({"success": True, "message": "Permit deleted successfully."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Add waypoint to a permit on a team route",
    request=TeamRouteWaypointWriteSerializer,
    responses={201: TeamRouteWaypointMutationResponseSerializer},
)
class TeamRouteWaypointListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def post(self, request, route_id, permit_id):
        from django.db import transaction
        from route.models import RoutePermit, PermitWaypoint
        from route.serializers import WaypointSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
        if not permit:
            return Response({"detail": "Permit not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRouteWaypointWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        count = permit.waypoints.count()
        requested_index = data.pop("index", None)
        insertion_index = requested_index if requested_index is not None else count + 1
        if insertion_index < 1 or insertion_index > count + 1:
            raise ValidationError({"index": f"Index must be between 1 and {count + 1}."})
        with transaction.atomic():
            _shift_waypoint_indexes_for_insert(permit, insertion_index)
            waypoint = PermitWaypoint.objects.create(
                permit=permit,
                route=route,
                index=insertion_index,
                **data,
            )
            _sync_route_waypoint_count(route)
        return Response(
            {
                "success": True,
                "message": "Waypoint added successfully.",
                "waypoint_id": waypoint.id,
                "data": WaypointSerializer(waypoint).data,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Team Dashboard - Route Management"],
    summary="Update or delete a waypoint on a team route",
    request=TeamRouteWaypointWriteSerializer,
    responses={200: TeamRouteWaypointMutationResponseSerializer},
)
class TeamRouteWaypointDetailView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "manage.route_history.team"

    def patch(self, request, route_id, permit_id, waypoint_id):
        from django.db import transaction
        from route.models import RoutePermit, PermitWaypoint
        from route.serializers import WaypointSerializer

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
        if not permit:
            return Response({"detail": "Permit not found."}, status=status.HTTP_404_NOT_FOUND)
        waypoint = PermitWaypoint.objects.filter(id=waypoint_id, permit=permit).first()
        if not waypoint:
            return Response({"detail": "Waypoint not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TeamRouteWaypointWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        waypoint_data = dict(serializer.validated_data)
        desired_index = waypoint_data.pop("index", None)
        with transaction.atomic():
            for field, value in waypoint_data.items():
                setattr(waypoint, field, value)
            waypoint.route = route
            waypoint.save()
            if desired_index is not None and desired_index != waypoint.index:
                _move_waypoint_to_index(permit, waypoint, desired_index)
                waypoint.refresh_from_db()
        return Response(
            {
                "success": True,
                "message": "Waypoint updated successfully.",
                "waypoint_id": waypoint.id,
                "data": WaypointSerializer(waypoint).data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, route_id, permit_id, waypoint_id):
        from django.db import transaction
        from route.models import RoutePermit, PermitWaypoint

        route = _get_team_route_or_404(request, route_id)
        if not route:
            return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
        permit = RoutePermit.objects.filter(id=permit_id, route=route).first()
        if not permit:
            return Response({"detail": "Permit not found."}, status=status.HTTP_404_NOT_FOUND)
        waypoint = PermitWaypoint.objects.filter(id=waypoint_id, permit=permit).first()
        if not waypoint:
            return Response({"detail": "Waypoint not found."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            waypoint.delete()
            _compact_waypoint_indexes(permit)
            _sync_route_waypoint_count(route)
        return Response({"success": True, "message": "Waypoint deleted successfully."}, status=status.HTTP_200_OK)
