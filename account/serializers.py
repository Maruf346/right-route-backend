from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import (
    validate_password
)
from rest_framework import serializers
from account.models import User, OTPVerification
from core.constants import OTPPurpose
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

class ContinueSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()

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
        attrs["user"] = user
        return attrs

    def send_login_otp(self):
        otp_code = "123456"
        OTPVerification.objects.create(
            user=self.validated_data["user"],
            otp_code=otp_code,
            purpose=OTPPurpose.LOGIN,
        )
        # send otp email here
        return True

class CreatePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(
            email=value
        ).exists():
            raise serializers.ValidationError(
                "Account already exists."
            )
        return value

    def validate(self, attrs):
        validate_password(
            attrs["password"]
        )
        return attrs

    def create_user(self):
        email = self.validated_data["email"]
        password = (self.validated_data["password"])
        user = User.objects.create_user(
            email=email,
            password=password,
        )
        otp_code = "123456"
        OTPVerification.objects.create(
            user=user,
            otp_code=otp_code,
            purpose=(
                OTPPurpose.REGISTER
            )
        )

        # send otp email here
        return user

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)

    def validate_email(self, value):
        return value.lower()
    
    def validate(self, attrs):
        email = attrs["email"]
        otp_code = (attrs["otp_code"])
        print("ot: ", otp_code)
        otp = OTPVerification.objects.filter(
            user__email=email,
            otp_code=otp_code,
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
        user.last_device_info = (request.headers.get("User-Agent"))
        user.save()
        self.user = user
        refresh = RefreshToken.for_user(user)
        return refresh

class ResendOTPSerializer(serializers.Serializer):
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

    def resend_otp(self):
        OTPVerification.objects.filter(
            user=self.user,
            is_verified=False,
        ).delete()
        otp_code = "123456"
        OTPVerification.objects.create(
            user=self.user,
            otp_code=otp_code,
            purpose=OTPPurpose.LOGIN,
        )
        # send email here
        return True

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


