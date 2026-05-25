from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from account.models import User
from rest_framework.exceptions import ValidationError
from .serializers import (
    ContinueSerializer,
    LoginSerializer,
    CreatePasswordSerializer,
    VerifyOTPSerializer,
)


class ContinueAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = ContinueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user_exists = User.objects.filter(
            email=email
        ).exists()
        return Response(
            {
                "success": True,
                "email": email,
                "is_registered": user_exists,
                "next_step": (
                    "LOGIN_PASSWORD"
                    if user_exists
                    else "CREATE_PASSWORD"
                )
            }
        )


class LoginAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)        
        serializer.send_login_otp()
        return Response(
            {
                "success": True,
                "message": "OTP sent successfully.",
                "next_step": "VERIFY_OTP"
            }
        )


class CreatePasswordAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = (CreatePasswordSerializer(data=request.data))
        serializer.is_valid(raise_exception=True)
        serializer.create_user()
        # email = serializer.validated_data["email"]
        # password = (serializer.validated_data["password"])

        # user = User.objects.create_user(
        #     email=email,
        #     password=password,
        # )

        # otp_code = "123456"

        # OTPVerification.objects.create(
        #     user=user,
        #     otp_code=otp_code,
        #     purpose=(
        #         OTPPurpose.REGISTER
        #     )
        # )

        # send otp email here

        return Response(
            {
                "success": True,
                "message":
                "Account created successfully.",
                "next_step":
                "VERIFY_OTP"
            },
            status=status.HTTP_201_CREATED
        )


class VerifyOTPAPIView(APIView):
    permission_classes = []
    
    def get_success_response(self, serializer, token):
        return Response(
            {
                "success": True,
                "message": "Authentication successful.",
                "data": {
                    "access": str(token.access_token),
                    "refresh": str(token),
                    "user": {
                        "id": serializer.get_user().id,
                        "email": serializer.get_user().email,
                    }
                }
            }
        )

    def post(self, request):
        try:
            serializer = VerifyOTPSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            token = serializer.get_token(request)
            return self.get_success_response(serializer, token)
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }
            )


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(
            {
                "success": True,
                "message": "Logout successful."
            }
        )


class RefreshTokenAPIView(TokenRefreshView):
    pass

class VerifyTokenAPIView(TokenVerifyView):
    def post(self, request, *args, **kwargs) -> Response:
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return Response(
                {
                    "status": False,
                    "message": "Token Valid!"
                }, status=status.HTTP_200_OK
            )
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "status": False,
                    "message": error
                }, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    "status": False,
                    "message": str(e)
                }, status=status.HTTP_400_BAD_REQUEST
            )
