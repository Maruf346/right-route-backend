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

    def generate_otp(self):
        otp_code = "123456"
        return otp_code
    
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
        # send otp email here
        return otp_object
    
    def create_user(self):
        email = self.validated_data["email"]
        password = (self.validated_data["password"])
        user = User.objects.create_user(
            email=email,
            password=password,
        )
        self.send_otp(user=user)
        return user

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
        otp_code = "123456"
        return otp_code
    
    def resend_otp(self):
        OTPVerification.objects.filter(user=self.user).delete()
        purpose = self.validated_data["purpose"]
        OTPVerification.objects.create(
            user=self.user,
            email=self.user.email,
            otp_code=self.generate_otp(),
            purpose=purpose
        )
        # send email here
        return True

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    for_log = serializers.BooleanField(required=False)

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
    
    # def create_or_get_device_info(self, request):
    #     user = self.get_user()
    #     return True
    
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

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate_email(self, value):
        return value.lower()

    # def create_or_get_device_info(self, request):
    #     user = self.get_user()
    #     return True
    
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
        otp_code = "123456"
        return otp_code
    
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
    
    # def create_or_get_device_info(self, request):
    #     user = self.get_user()
    #     last_device_info = (request.headers.get("User-Agent"))
    #     return True
    
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


