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
from .admin_serializers import AdminLoginSerializer
from .utils import OwnAPIView


class AdminLoginView(OwnAPIView):
    serializer_class = AdminLoginSerializer
    permission_classes = []
    
    def success_response(self, serializer):
        data = serializer.validated_data
        user = data["user"]

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": {
                    "id": user.id,
                    "email": user.email,
                    "user_type": user.user_type,
                    "access_token": data["access"],
                    "refresh_token": data["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )


