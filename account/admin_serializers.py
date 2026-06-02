from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import (
    validate_password
)
from rest_framework import serializers
from account.models import User, OTPVerification
from core.constants import OTPPurpose
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from core.constants import UserType

class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )

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

        refresh = RefreshToken.for_user(user)

        return {
            "user": user,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


