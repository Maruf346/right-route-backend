from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from account.models import AdminUserProfile, User, OTPVerification
from core.constants import OTPPurpose, UserStatus
from core.permissions import (
    ADMIN_DASHBOARD_PERMISSIONS,
    get_admin_dashboard_permissions,
)
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


class AdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    access_status = serializers.SerializerMethodField()
    is_superadmin = serializers.BooleanField(source="is_superuser", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "permissions",
            "access_status",
            "is_superadmin",
            "is_active",
            "last_login",
            "last_login_ip",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField)
    def get_full_name(self, obj):
        profile = getattr(obj, "admin_profile", None)
        if profile:
            return profile.full_name
        return obj.email

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_phone(self, obj):
        profile = getattr(obj, "admin_profile", None)
        return profile.phone if profile else None

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, obj):
        return get_admin_dashboard_permissions(obj)

    @extend_schema_field(serializers.CharField)
    def get_access_status(self, obj):
        return "Allowed" if obj.is_active else "Locked"


class AdminUserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True)
    is_superadmin = serializers.BooleanField(default=False)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(item, item) for item in ADMIN_DASHBOARD_PERMISSIONS]),
        required=False,
        allow_empty=True,
    )

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Admin user with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs.get("is_superadmin"):
            attrs["permissions"] = []
        else:
            attrs["permissions"] = attrs.get("permissions", [])
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        permissions = validated_data.pop("permissions", [])
        full_name = validated_data.pop("full_name")
        phone = validated_data.pop("phone", None)
        password = validated_data.pop("password")
        is_superadmin = validated_data.pop("is_superadmin", False)

        with transaction.atomic():
            user = User.objects.create_user(
                email=validated_data["email"],
                password=password,
                user_type=UserType.ADMIN,
                status=UserStatus.ACTIVE,
                is_active=True,
                is_staff=True,
                is_superuser=is_superadmin,
                is_email_verified=True,
            )
            AdminUserProfile.objects.create(
                user=user,
                full_name=full_name,
                phone=phone,
                permissions_json=permissions,
                created_by=request.user,
                updated_by=request.user,
            )
        return user


class AdminUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True, required=False)
    is_superadmin = serializers.BooleanField(required=False)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(item, item) for item in ADMIN_DASHBOARD_PERMISSIONS]),
        required=False,
        allow_empty=True,
    )

    def validate_email(self, value):
        value = value.lower()
        if User.objects.exclude(id=self.instance.id).filter(email=value).exists():
            raise serializers.ValidationError("Admin user with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs.get("is_superadmin") is True:
            attrs["permissions"] = []
        return attrs

    def update(self, instance, validated_data):
        request = self.context["request"]
        profile, _ = AdminUserProfile.objects.get_or_create(
            user=instance,
            defaults={
                "full_name": instance.email,
                "created_by": request.user,
            },
        )

        with transaction.atomic():
            if "email" in validated_data:
                instance.email = validated_data["email"]
            if "password" in validated_data:
                instance.set_password(validated_data["password"])
            if "is_superadmin" in validated_data:
                instance.is_superuser = validated_data["is_superadmin"]
                if instance.is_superuser:
                    profile.permissions_json = []

            instance.user_type = UserType.ADMIN
            instance.is_staff = True
            instance.save()

            if "full_name" in validated_data:
                profile.full_name = validated_data["full_name"]
            if "phone" in validated_data:
                profile.phone = validated_data["phone"]
            if "permissions" in validated_data and not instance.is_superuser:
                profile.permissions_json = validated_data["permissions"]
            profile.updated_by = request.user
            profile.save()

        return instance


class AdminUserListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    count = serializers.IntegerField()
    data = AdminUserSerializer(many=True)


class AdminUserRetrieveResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = AdminUserSerializer()


class AdminUserCreateResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminUserSerializer()


class AdminUserUpdateResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminUserSerializer()


class AdminUserDeleteResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class AdminUserAccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminUserSerializer()


