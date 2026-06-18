from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework import status
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from account.models import User, OTPVerification
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from .serializers import (
    ContinueSerializer,
    LoginSerializer,
    CreatePasswordSerializer,
    VerifyOTPSerializer, ChangePasswordSerializer,
    ResendOTPSerializer, ChangeEmailSerializer,
    
    ResetPasswordSerializer, ForgetPasswordSerializer
)
from .utils import OwnAPIView
from django.db import transaction
from core.constants import OTPPurpose

class DeviceInfoView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get(self, request, *args, **kwargs):
        data = request.data
        print("data: ", data)
        return Response(
            {
                "success": True,
                "is_device_register": True
            }
        )
    
    def create_or_get_device_info(self):
        user = self.request.user
        last_device_info = (self.request.headers.get("User-Agent"))
        return True
    
    def post(self, request, *args, **kwargs):
        data = request.data
        self.create_or_get_device_info()
        print("data: ", data)
        return Response(
            {
                "success": True,
                "is_device_register": True
            }
        )


class ContinueAPIView(OwnAPIView):
    serializer_class = ContinueSerializer
    permission_classes = []
    
    def generate_otp(self):
        otp_code = "123456"
        return otp_code
    
    def send_otp(self, email: str, purpose: OTPPurpose, user=None) -> OTPVerification:
        OTPVerification.objects.filter(email=email).delete()        
        otp_object = OTPVerification.objects.create(
            user=user,
            email=email,
            purpose=purpose,
            otp_code=self.generate_otp()
            
        )
        # send otp email here
        return otp_object
    
    def success_response(self, serializer):
        email = serializer.validated_data["email"]
        user_exists = User.objects.filter(
            email=email
        ).exists()
        if user_exists:
            otp_object = self.send_otp(
                email=email,
                purpose=OTPPurpose.LOGIN,
                user=User.objects.get(email=email)
            )
        
        return Response(
            {
                "success": True,
                "email": email,
                "is_registered": user_exists,
                "next_step": ("OTP_VERIFY" if user_exists else "CREATE_PASSWORD")
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
                "next_step": "OTP_VERIFY"
            },
            status=status.HTTP_201_CREATED
        )

class ResendOTPAPIView(OwnAPIView):
    serializer_class = ResendOTPSerializer
    permission_classes = []

    def success_response(self, serializer):
        serializer.resend_otp()
        return Response(
            {
                "success": True,
                "detail": "OTP re-sent successfully."
            }, status=status.HTTP_200_OK
        )

class VerifyOTPAPIView(APIView):
    permission_classes = []
    
    def post(self, request, *args, **kwargs) -> Response:
        try:
            serializer = VerifyOTPSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            otp = serializer.validated_data.get("otp")
            if otp.purpose == OTPPurpose.LOGIN:
                return self.login_response(serializer)
            elif otp.purpose == OTPPurpose.REGISTER:
                return self.registration_response(serializer)
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
    
    def login_response(self, serializer):
        get_verified = serializer.get_verified(self.request)
        return Response(
            {
                "success": True,
                "next_step": ("SUBMIT_PASSWORD")
            }
        )
    
    def registration_response(self, serializer):
        token = serializer.get_token(self.request)
        return Response(
            {
                "success": True,
                "detail": "Registration successful.",
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

class LoginAPIView(OwnAPIView):
    serializer_class = LoginSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        with transaction.atomic():
            token = serializer.get_token(self.request)
            return Response(
                {
                    "success": True,
                    "detail": "Login successful.",
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


# Forget and Reset Password---
class ForgetPasswordView(OwnAPIView):
    serializer_class = ForgetPasswordSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        with transaction.atomic():
            serializer.send_otp()
            return Response(
                {
                    "success": True,
                    "detail": "Password Reset OTP Send.",
                    "email": serializer.validated_data["email"],
                    "next_step": "RESET_PASSWORD"
                }
            )

class ResetPasswordView(OwnAPIView):
    serializer_class = ResetPasswordSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        token = serializer.get_token(self.request)
        return Response(
            {
                "success": True,
                "detail": "Registration successful.",
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



class ChangeEmailAPIView(APIView):
    serializer_class = ChangeEmailSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.serializer_class(data=request.data,context={"request": request})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(
                    {
                        "success": True,
                        "detail": "Email updated successfully."
                    },
                    status=status.HTTP_200_OK
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

class AccountDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = self.request.user
        user.delete()
        return Response(
            {
                "success": True,
                "detail": "Account Deleted successful."
            }, status=status.HTTP_200_OK
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





