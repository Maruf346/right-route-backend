from django.contrib.auth import authenticate
from rest_framework import serializers
from account.models import User, OTPVerification
from core.constants import OTPPurpose
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from core.constants import UserType
import random

from .emailsend import EmailOTPSend

class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, required=False)
    otp_code = serializers.CharField(max_length=6, write_only=True, required=False)

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        otp_code = attrs.get("otp_code")

        if otp_code:
            return self.validate_otp_login(attrs)

        if not password:
            raise serializers.ValidationError(
                {"password": "Password is required."}
            )

        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )

        self.validate_admin_user(user)
        self.send_otp(user)

        return {
            "user": user,
            "email": user.email,
            "next_step": "OTP_VERIFY",
        }

    def validate_admin_user(self, user):
        if not user:
            raise serializers.ValidationError(
                "Invalid email or password."
            )
        if not user.is_staff:
            raise serializers.ValidationError(
                "Admin access required."
            )
        if not user.is_active:
            raise serializers.ValidationError(
                "Account is inactive."
            )
        if user.user_type != UserType.ADMIN:
            raise serializers.ValidationError(
                "Only Admin can Login."
            )

    def generate_otp(self):
        return str(random.randint(100000, 999999))

    def send_otp(self, user):
        OTPVerification.objects.filter(
            user=user,
            email=user.email,
            purpose=OTPPurpose.LOGIN,
            is_verified=False,
        ).delete()
        otp_object = OTPVerification.objects.create(
            user=user,
            email=user.email,
            purpose=OTPPurpose.LOGIN,
            otp_code=self.generate_otp(),
        )
        EmailOTPSend(otp_object)
        return otp_object

    def validate_otp_login(self, attrs):
        email = attrs.get("email")
        otp_code = attrs.get("otp_code")
        user = User.objects.filter(email=email).first()

        self.validate_admin_user(user)

        otp = OTPVerification.objects.filter(
            user=user,
            email=email,
            otp_code=otp_code,
            purpose=OTPPurpose.LOGIN,
            is_verified=False,
        ).first()

        if not otp:
            raise serializers.ValidationError({"otp_code": "Invalid OTP."})
        if otp.is_expired:
            raise serializers.ValidationError({"otp_code": "OTP expired."})

        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save(update_fields=["is_verified", "verified_at"])

        user.last_login_ip = self.context["request"].META.get("REMOTE_ADDR")
        user.is_email_verified = True
        user.save(update_fields=["last_login_ip", "is_email_verified"])

        refresh = RefreshToken.for_user(user)

        return {
            "user": user,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "next_step": "LOGIN_COMPLETE",
        }


class AdminLoginPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminLoginOTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6, write_only=True)


class AdminLoginOTPDataSerializer(serializers.Serializer):
    email = serializers.EmailField()
    next_step = serializers.CharField()


class AdminLoginTokenDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    user_type = serializers.CharField()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()


class AdminLoginOTPResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminLoginOTPDataSerializer()


class AdminLoginSuccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminLoginTokenDataSerializer()


