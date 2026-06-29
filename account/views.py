from django.contrib.auth import logout
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework import status
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from account.models import User, OTPVerification, UserLogDevice, TeamMemberInvite, TeamMember
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from .serializers import (
    ContinueSerializer,
    LoginSerializer,
    CreatePasswordSerializer,
    VerifyOTPSerializer,
    ChangePasswordSerializer,
    ResendOTPSerializer,
    ChangeEmailSerializer,
    ResetPasswordSerializer,
    ForgetPasswordSerializer,
    
    CurrentUserSerializer, DeviceInfoSerializer
)
from .utils import OwnAPIView
from django.db import transaction
from core.constants import OTPPurpose, TeamMemberInviteStatus
import random
from .emailsend import EmailOTPSend
from django.contrib.auth.hashers import identify_hasher
from django.utils import timezone


class DeviceInfoView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_device(self, device_id):
        try:
            return get_object_or_404(UserLogDevice, device_id=device_id)
        except:
            return None

    def get(self, request, *args, **kwargs):
        serializer = DeviceInfoSerializer(data=request.data)
        device_name = request.headers.get("User-Agent")
        serializer.is_valid(raise_exception=True)
        
        device_info = self.get_device(device_id=serializer.validated_data["device_id"])
        if device_info is None:
            return Response(
                {
                    "success": True,
                    "device_register": False,
                    "device_secure": False
                }, status=status.HTTP_200_OK
            )
        else:
            if device_info.device_name != device_name:
                return Response(
                    {
                        "success": True,
                        "device_register": True,
                        "device_secure": False,
                        "device_user_email": device_info.user.email
                    }, status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {
                        "success": True,
                        "device_register": True,
                        "device_secure": True,
                        "device_user_email": device_info.user.email
                    }, status=status.HTTP_200_OK
                )

    def post(self, request):
        try:
            device_name = request.headers.get("User-Agent")
            print("device_name: ", device_name)
            serializer = DeviceInfoSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            device, created = UserLogDevice.objects.update_or_create(
                user=request.user,
                device_id=serializer.validated_data["device_id"],
                defaults={
                    "device_name": device_name,
                }
            )
            return Response({
                "success": True,
                "message": (
                    "Device registered"
                    if created
                    else "Device updated"
                )
            })
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



class ContinueAPIView(OwnAPIView):
    serializer_class = ContinueSerializer
    permission_classes = []

    def generate_otp(self):
        return str(random.randint(100000, 999999))

    def send_otp(self, email: str, purpose: OTPPurpose, user=None) -> OTPVerification:
        OTPVerification.objects.filter(email=email, purpose=OTPPurpose.LOGIN).delete()
        otp_object = OTPVerification.objects.create(
            user=user, email=email, purpose=purpose, otp_code=self.generate_otp()
        )
        
        EmailOTPSend(otp_object)
        return otp_object

    def user_has_valid_password(self, email):
        try:
            user = User.objects.get(email=email)
            identify_hasher(user.password)
            return True
        except:
            return False
    
    def success_response(self, serializer):
        email = serializer.validated_data["email"]
        register_user_exists = self.user_has_valid_password(email)
        if register_user_exists:
            otp_object = self.send_otp(
                email=email,
                purpose=OTPPurpose.LOGIN,
                user=User.objects.get(email=email),
            )
        return Response(
            {
                "success": True,
                "email": email,
                "is_registered": register_user_exists,
                "next_step": ("OTP_VERIFY" if register_user_exists else "CREATE_PASSWORD"),
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
                "next_step": "OTP_VERIFY",
            },
            status=status.HTTP_201_CREATED,
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
                        },
                    },
                }
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
                {"success": False, "detail": error}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

    def login_response(self, serializer):
        get_verified = serializer.get_verified(self.request)
        return Response({"success": True, "next_step": ("SUBMIT_PASSWORD")})

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
                    },
                },
            }
        )

class ResendOTPAPIView(OwnAPIView):
    serializer_class = ResendOTPSerializer
    permission_classes = []

    def success_response(self, serializer):
        serializer.resend_otp()
        return Response(
            {"success": True, "detail": "OTP re-sent successfully."},
            status=status.HTTP_200_OK,
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
                    "next_step": "RESET_PASSWORD",
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
                    },
                },
            }
        )

class ChangeEmailAPIView(APIView):
    serializer_class = ChangeEmailSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.serializer_class(
                    data=request.data, context={"request": request}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(
                    {"success": True, "detail": "Email updated successfully."},
                    status=status.HTTP_200_OK,
                )
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {"success": False, "detail": error}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

class AccountDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = self.request.user
        user.delete()
        return Response(
            {"success": True, "detail": "Account Deleted successful."},
            status=status.HTTP_200_OK,
        )

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"success": True, "detail": "Logout successful."})

class RefreshTokenAPIView(TokenRefreshView):
    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            return Response(
                {"success": True, "data": serializer.validated_data},
                status=status.HTTP_200_OK,
            )
        except TokenError as e:
            return Response(
                {"success": False, "detail": str(e)},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except Exception as e:
            return Response(
                {"success": False, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

class VerifyTokenAPIView(TokenVerifyView):
    def post(self, request, *args, **kwargs) -> Response:
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return Response(
                {"success": True, "detail": "Token Valid!"}, status=status.HTTP_200_OK
            )
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {"success": False, "detail": error}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
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
                "mail": user.email if user else None,
            },
            status=status.HTTP_200_OK,
        )



class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = CurrentUserSerializer(user)
        return Response({
            "success": True,
            "data": serializer.data
        })

class AcceptTeamMemberInvitation(APIView):
    permission_classes = [IsAuthenticated]
    
    def validate_invitation(self, invitation_uuid) -> TeamMemberInvite:
        try:
            invitation = (
                TeamMemberInvite.objects
                .select_for_update()
                .select_related("team", "team_member_object")
                .get(uuid=invitation_uuid)
            )
        except TeamMemberInvite.DoesNotExist:
            raise ValidationError("Invitation not found.")

        if invitation.invited_to != self.request.user:
            raise PermissionDenied("This invitation does not belong to you.")

        if invitation.status != TeamMemberInviteStatus.PENDING:
            raise ValidationError(f"Invite already {invitation.status.capitalize()}.")
        if invitation.expires_at < timezone.now():
            raise ValidationError("Invitation has expired.")
        return invitation
    
    def post(self, request, *args, **kwargs):
        data = request.data
        invitation_uuid = data.get("invitation_uuid", None)
        action = data.get("action", None)
        ALLOWED_ACTIONS = {
            TeamMemberInviteStatus.ACCEPT,
            TeamMemberInviteStatus.REJECT,
        }
        
        if not invitation_uuid:
            return Response(
                {
                    "success": False,
                    "message": "Invitation UUID is required."
                }, status=status.HTTP_400_BAD_REQUEST
            )
        if not action:
            return Response(
                {
                    "success": False,
                    "message": "Invitation action be submit."
                }, status=status.HTTP_400_BAD_REQUEST
            )
        if action.strip().upper() not in ALLOWED_ACTIONS:
            return Response(
                {
                    "success": False,
                    "message": "Wrong invation status submit."
                }, status=status.HTTP_400_BAD_REQUEST
            )
        
        action_status = action.strip().upper()
        invitation = self.validate_invitation(invitation_uuid)
        team_member_object = invitation.team_member_object
        
        with transaction.atomic():
            if (
                action_status == TeamMemberInviteStatus.ACCEPT
                and TeamMember.objects.filter(
                    team=invitation.team,
                    user=request.user,
                    status=True,
                ).exists()
            ):
                raise ValidationError("You are already a member of this team.")
            
            invitation.status = action_status
            invitation.show_popup = False
            invitation.save(update_fields=["status", "show_popup"])
            
            if action_status == TeamMemberInviteStatus.ACCEPT:
                team_member_object.status = True
                team_member_object.save(update_fields=["status"])
            else:
                team_member_object.delete()
            
            message = (
                "Team invitation accepted successfully."
                if action_status == TeamMemberInviteStatus.ACCEPT
                else "Team invitation rejected successfully."
            )
            return Response(
                {
                    "success": True,
                    "message": message
                }
            )
