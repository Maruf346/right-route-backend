from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import (
    validate_password
)
from rest_framework import serializers
from account.models import User, OTPVerification
from core.constants import OTPPurpose, CurrentPlanType, PlanType
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
import random
from subscription.models import UserSubscription
from .models import Team, TeamMember, TeamMemberInvite
from core.constants import TeamMemberStatus, UserSubscriptionStatus
from .emailsend import EmailOTPSend
from django.db import transaction
from django.contrib.auth.hashers import identify_hasher


class ContinueSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()

class CreatePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def user_has_valid_password(self, user):
        try:
            identify_hasher(user.password)
            return True
        except:
            return False
    
    def validate_email(self, value):
        value = value.lower()
        user = User.objects.filter(email=value)
        if User.objects.filter(email=value).exists():
            user = User.objects.get(email=value)
            if self.user_has_valid_password(user):
                raise serializers.ValidationError(
                    "Account already exists."
                )
        return value

    def validate(self, attrs):
        validate_password(
            attrs["password"]
        )
        return attrs

    def generate_otp(self):
        return str(random.randint(100000, 999999))
    
    def send_otp(self, user) -> OTPVerification:
        OTPVerification.objects.filter(email=user.email).delete()        
        otp_object = OTPVerification.objects.create(
            user=user,
            email=user.email,
            purpose=(
                OTPPurpose.REGISTER
            ),
            otp_code=self.generate_otp()
        )
        EmailOTPSend(otp_object)
        return otp_object
    
    def create_user(self):
        with transaction.atomic():
            email = self.validated_data["email"]
            password = (self.validated_data["password"])
            user, created = User.objects.get_or_create(email=email)
            user.set_password(password)
            user.save(update_fields=["password"])
            
            self.send_otp(user=user)
            return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate_email(self, value):
        return value.lower()
    
    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        user = authenticate(
            email=email,
            password=password
        )
        if not user:
            raise serializers.ValidationError(
                "Invalid credentials."
            )
        if not user.is_active:
            raise serializers.ValidationError(
                "Account disabled."
            )
        self.user = user
        return attrs
    
    def get_user(self):
        return self.user

    def get_token(self, request):
        user = self.get_user()
        user.last_login_ip = (request.META.get("REMOTE_ADDR"))
        user.save()
        refresh = RefreshToken.for_user(user)
        # self.create_or_get_device_info(request)
        return refresh

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    purpose = serializers.ChoiceField(required=True, choices=OTPPurpose.choices)

    def validate_email(self, value):
        value = value.lower()
        user = User.objects.filter(
            email=value
        ).first()
        if not user:
            raise serializers.ValidationError(
                "Account not found."
            )
        self.user = user
        return value
    
    def validate(self, attrs):
        email = attrs["email"]
        purpose = attrs["purpose"]
        otp_code = (attrs["otp_code"])
        otp = OTPVerification.objects.filter(
            user__email=email,
            otp_code=otp_code,
            purpose=purpose,
            is_verified=False,
        ).first()
        if not otp:
            raise serializers.ValidationError({"otp": "Invalid OTP"})
        if otp.is_expired:
            raise serializers.ValidationError({"otp": "OTP expired"})
        attrs["otp"] = otp
        return super().validate(attrs)
    
    def get_user(self):
        return self.user
    
    def get_token(self, request):
        otp = self.validated_data["otp"]
        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        user = otp.user
        user.is_email_verified = True
        user.last_login_ip = (request.META.get("REMOTE_ADDR"))
        # user.last_device_info = (request.headers.get("User-Agent"))
        user.save()
        self.user = user
        refresh = RefreshToken.for_user(user)
        
        # self.create_or_get_device_info(request)
        return refresh

    def get_verified(self, request):
        otp = self.validated_data["otp"]
        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()
        
        user = otp.user
        user.is_email_verified = True
        user.last_login_ip = (request.META.get("REMOTE_ADDR"))
        user.save()
        self.user = user

        # self.create_or_get_device_info(request)
        return request

class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)

    def validate_email(self, value):
        value = value.lower()
        user = User.objects.filter(
            email=value
        ).first()
        if not user:
            raise serializers.ValidationError(
                "Account not found."
            )
        self.user = user
        return value

    def validate_purpose(self, value):
        if value not in [OTPPurpose.LOGIN, OTPPurpose.REGISTER, OTPPurpose.RESET]:
            raise serializers.ValidationError("Wrong Type Input")
        return value
    
    def generate_otp(self):
        return str(random.randint(100000, 999999))
    
    def resend_otp(self):
        OTPVerification.objects.filter(user=self.user).delete()
        purpose = self.validated_data["purpose"]
        otp_object = OTPVerification.objects.create(
            user=self.user,
            email=self.user.email,
            otp_code=self.generate_otp(),
            purpose=purpose
        )
        EmailOTPSend(otp_object)
        return True

# Forget and Reset Password---
class ForgetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.lower()
        user = User.objects.filter(
            email=value
        ).first()
        if not user:
            raise serializers.ValidationError(
                "Account not found."
            )
        self.user = user
        return value

    def generate_otp(self):
        return str(random.randint(100000, 999999))
    
    def send_otp(self) -> OTPVerification:
        email = self.validated_data["email"]
        user = User.objects.get(email=email)
        OTPVerification.objects.filter(email=email).delete()
        otp_object = OTPVerification.objects.create(
            user=user,
            email=user.email,
            purpose=(
                OTPPurpose.RESET
            ),
            otp_code=self.generate_otp()
        )
        # send otp email here
        return otp_object

class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)

    def validate_email(self, value):
        value = value.lower()
        user = User.objects.filter(
            email=value
        ).first()
        if not user:
            raise serializers.ValidationError(
                "Account not found."
            )
        self.user = user
        return value
    
    def validate(self, attrs):
        email = attrs["email"]
        otp_code = (attrs["otp_code"])
        
        otp = OTPVerification.objects.filter(
            user__email=email,
            otp_code=otp_code,
            purpose=OTPPurpose.RESET,
            is_verified=False,
        ).first()
        
        if not otp:
            raise serializers.ValidationError({"otp": "Invalid OTP"})
        if otp.is_expired:
            raise serializers.ValidationError({"otp": "OTP expired"})
        attrs["otp"] = otp
        return super().validate(attrs)
    
    def get_user(self):
        return self.user

    def get_token(self, request):
        otp = self.validated_data["otp"]
        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        user = otp.user
        user.last_login_ip = (request.META.get("REMOTE_ADDR"))
        user.save()
        self.user = user
        refresh = RefreshToken.for_user(user)
        
        # self.create_or_get_device_info(request)
        return refresh

class ChangeEmailSerializer(serializers.Serializer):
    new_email = serializers.EmailField()

    def validate_new_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Email already exists."
            )
        return value

    def save(self):
        user = self.context["request"].user
        user.email = self.validated_data["new_email"]
        user.is_email_verified = False
        user.save(
            update_fields=["email", "is_email_verified"]
        )
        return user

class ChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=6)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def change_password(self, request):
        new_password = self.validated_data["new_password"]
        user = request.user
        user.plain_password = new_password
        user.set_password(new_password)
        user.save()
        return user





class CurrentUserSerializer(serializers.ModelSerializer):
    current_plan_type = serializers.SerializerMethodField()
    team_invitation_popup = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "current_plan_type", "team_invitation_popup"]
    
    def get_current_plan_type(self, user):
        membership = (
            TeamMember.objects
            .select_related("team", "team__owner")
            .filter(
                user=user,
                status=True
            )
            .first()
        )

        if membership:
            owner_team_subscription = (
                UserSubscription.objects
                .filter(
                    user=membership.team.owner,
                    team=membership.team,
                    plan__plan_type=PlanType.TEAM,
                )
                .order_by("-created_at")
                .first()
            )

            if owner_team_subscription and owner_team_subscription.is_valid:
                return "TEAM_MEMBER"

        # 2. Check User Active Subscription
        subscription = (
            UserSubscription.objects
            .filter(user=user)
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )

        if not subscription or not subscription.is_valid:
            return "NONE"

        # 3. Active Team Subscription
        if subscription.plan.plan_type == PlanType.TEAM:
            return "TEAM_MANAGER"

        # 4. Active Individual Subscription
        if subscription.plan.plan_type == PlanType.INDIVIDUAL:
            return "INDIVIDUAL"

        return "NONE"
    
    def get_team_invitation_popup(self, user):
        invite = (
            TeamMemberInvite.objects.select_related("team")
            .filter(invited_to=user, status=TeamMemberStatus.PENDING, show_popup=True)
            .order_by("-created_at")
            .first()
        )
        
        if not invite:
            return None

        return {
            "uuid": str(invite.uuid),
            "team_name": invite.team.name,
            "expires_at": invite.expires_at,
            "show_popup": invite.show_popup,
        }


class DeviceInfoSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=255)

    def validate_device_id(self, value):
        return value.strip()



