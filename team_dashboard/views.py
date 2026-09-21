from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from team_dashboard.permissions import (
    IsTeamDashboardUser,
    get_team_for_user,
    get_user_team_permissions,
)
from team_dashboard.utils import (
    generate_and_send_team_otp,
    mask_email_address,
)
from team_dashboard.serializers import (
    TeamLoginRequestSerializer,
    TeamVerifyOTPRequestSerializer,
    TeamResendOTPRequestSerializer,
    TeamInfoSerializer,
    TeamLoginOTPResponseSerializer,
    TeamLoginSuccessResponseSerializer,
    TeamDashboardUserSessionSerializer,
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
