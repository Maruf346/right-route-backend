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
from .serializers import (
    ContinueSerializer,
    LoginSerializer,
    CreatePasswordSerializer,
    VerifyOTPSerializer, ChangePasswordSerializer
)
from .utils import OwnAPIView


class ContinueAPIView(OwnAPIView):
    serializer_class = ContinueSerializer
    permission_classes = []
    
    def success_response(self, serializer):  
        email = serializer.validated_data["email"]
        user_exists = User.objects.filter(
            email=email
        ).exists()   
        return Response(
            {
                "success": True,
                "email": email,
                "is_registered": user_exists,
                "next_step": ( "LOGIN_PASSWORD" if user_exists else "CREATE_PASSWORD"
                )
            }
        )

class LoginAPIView(OwnAPIView):
    serializer_class = LoginSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        serializer.send_login_otp()
        return Response(
            {
                "success": True,
                "detail": "OTP sent successfully.",
                "next_step": "VERIFY_OTP"
            }
        )

class CreatePasswordAPIView(OwnAPIView):
    serializer_class = CreatePasswordSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        serializer.create_user()
        return Response(
            {
                "success": True,
                "detail": "Account created successfully.",
                "next_step": "VERIFY_OTP"
            },
            status=status.HTTP_201_CREATED
        )

class VerifyOTPAPIView(OwnAPIView):
    serializer_class = VerifyOTPSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        token = serializer.get_token(self.request)
        return Response(
            {
                "success": True,
                "detail": "Authentication successful.",
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

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(
            {
                "success": True,
                "detail": "Logout successful."
            }
        )


class RefreshTokenAPIView(TokenRefreshView):
    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            return Response(
                {
                    "success": True,
                    "data": serializer.validated_data
                }, status=status.HTTP_200_OK
            )
        except TokenError as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e)
                }, status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e)
                }, status=status.HTTP_400_BAD_REQUEST
            )

class VerifyTokenAPIView(TokenVerifyView):
    def post(self, request, *args, **kwargs) -> Response:
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return Response(
                {
                    "success": True,
                    "detail": "Token Valid!"
                }, status=status.HTTP_200_OK
            )
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error
                }, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e)
                }, status=status.HTTP_400_BAD_REQUEST
            )


class ChangePasswordView(OwnAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]
    
    def success_response(self, serializer):
        user = serializer.change_password(self.request)
        return Response(
            {
                "success": True,
                "message": "Password changed successfully",
                "mail": user.email if user else None
            }, status=status.HTTP_200_OK
        )


