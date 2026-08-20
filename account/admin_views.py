from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from account.models import User
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from .admin_serializers import (
    AdminLoginOTPRequestSerializer,
    AdminLoginOTPResponseSerializer,
    AdminLoginPasswordRequestSerializer,
    AdminLoginSerializer,
    AdminLoginSuccessResponseSerializer,
)
from .utils import OwnAPIView


class AdminLoginView(OwnAPIView):
    serializer_class = AdminLoginSerializer
    permission_classes = []

    @extend_schema(
        tags=["Auth - Admin"],
        operation_id="admin_login",
        summary="Admin login with email OTP verification",
        description=(
            "Step 1: submit `email` and `password` to send a 6 digit verification code. "
            "Step 2: submit `email` and `otp_code` to complete login and receive JWT tokens."
        ),
        request=PolymorphicProxySerializer(
            component_name="AdminLoginRequest",
            serializers=[
                AdminLoginPasswordRequestSerializer,
                AdminLoginOTPRequestSerializer,
            ],
            resource_type_field_name=None,
        ),
        examples=[
            OpenApiExample(
                "Step 1 - Request OTP",
                value={"email": "admin@example.com", "password": "password123"},
                request_only=True,
            ),
            OpenApiExample(
                "Step 2 - Verify OTP",
                value={"email": "admin@example.com", "otp_code": "123456"},
                request_only=True,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=PolymorphicProxySerializer(
                    component_name="AdminLoginResponse",
                    serializers=[
                        AdminLoginOTPResponseSerializer,
                        AdminLoginSuccessResponseSerializer,
                    ],
                    resource_type_field_name=None,
                ),
                description=(
                    "Returns either `next_step=OTP_VERIFY` after password validation, "
                    "or JWT tokens after OTP verification."
                ),
            ),
            400: OpenApiResponse(description="Invalid credentials, invalid OTP, or expired OTP."),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
    
    def success_response(self, serializer):
        data = serializer.validated_data
        user = data["user"]

        if data.get("next_step") == "OTP_VERIFY":
            return Response(
                {
                    "success": True,
                    "message": "Verification code sent.",
                    "data": {
                        "email": data["email"],
                        "next_step": "OTP_VERIFY",
                    },
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": {
                    "id": user.id,
                    "email": user.email,
                    "user_type": user.user_type,
                    "access_token": data["access"],
                    "refresh_token": data["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )


