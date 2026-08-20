from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from account.models import User
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from .admin_serializers import *
from core.constants import LogStatus, NotifyLogAction, UserStatus, UserType
from core.permissions import HasAdminDashboardPermission
from notification.models import ActivityLog
from .utils import OwnAPIView


class AdminLoginView(OwnAPIView):
    serializer_class = AdminLoginSerializer
    permission_classes = []

    @extend_schema(
        tags=["Auth - Admin"],
        operation_id="admin_login",
        summary="Admin login with email OTP verification",
        description=(
            "Step 1: submit `email` and `password` to send a 6 digit verification code. "
            "Step 2: submit `email` and `otp_code` to complete login and receive JWT tokens."
        ),
        request=PolymorphicProxySerializer(
            component_name="AdminLoginRequest",
            serializers=[
                AdminLoginPasswordRequestSerializer,
                AdminLoginOTPRequestSerializer,
            ],
            resource_type_field_name=None,
        ),
        examples=[
            OpenApiExample(
                "Step 1 - Request OTP",
                value={"email": "admin@example.com", "password": "password123"},
                request_only=True,
            ),
            OpenApiExample(
                "Step 2 - Verify OTP",
                value={"email": "admin@example.com", "otp_code": "123456"},
                request_only=True,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=PolymorphicProxySerializer(
                    component_name="AdminLoginResponse",
                    serializers=[
                        AdminLoginOTPResponseSerializer,
                        AdminLoginSuccessResponseSerializer,
                    ],
                    resource_type_field_name=None,
                ),
                description=(
                    "Returns either `next_step=OTP_VERIFY` after password validation, "
                    "or JWT tokens after OTP verification."
                ),
            ),
            400: OpenApiResponse(description="Invalid credentials, invalid OTP, or expired OTP."),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
    
    def success_response(self, serializer):
        data = serializer.validated_data
        user = data["user"]

        if data.get("next_step") == "OTP_VERIFY":
            return Response(
                {
                    "success": True,
                    "message": "Verification code sent.",
                    "data": {
                        "email": data["email"],
                        "next_step": "OTP_VERIFY",
                    },
                },
                status=status.HTTP_200_OK,
            )

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


@extend_schema(
    tags=["Admin - User Management"],
)
class AdminUserViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    serializer_class = AdminUserSerializer
    queryset = User.objects.filter(
        user_type=UserType.ADMIN,
        is_staff=True,
    ).select_related("admin_profile").order_by("-is_superuser", "-created_at")
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "admin_profile__full_name", "admin_profile__phone"]
    ordering_fields = [
        "created_at",
        "updated_at",
        "email",
        "last_login",
        "is_superuser",
    ]

    def get_serializer_class(self):
        if self.action == "create":
            return AdminUserCreateSerializer
        if self.action in ["update", "partial_update"]:
            return AdminUserUpdateSerializer
        return AdminUserSerializer

    def get_required_admin_permissions(self):
        if self.action in ["list", "retrieve"]:
            return ["admin_users.list"]
        if self.action == "create":
            return ["admin_users.add"]
        return ["admin_users"]

    def log_admin_action(self, action, target_user, message, metadata=None):
        ActivityLog.objects.create(
            user=self.request.user,
            action=action,
            message=message,
            status=LogStatus.SUCCESS,
            entity_type=ContentType.objects.get_for_model(target_user),
            entity_id=target_user.id,
            ip_address=self.request.META.get("REMOTE_ADDR") or "0.0.0.0",
            device_info=self.request.headers.get("User-Agent", ""),
            metadata_json=metadata or {},
        )

    def serialize_admin_user(self, user):
        return AdminUserSerializer(user, context={"request": self.request}).data

    def get_target_access_error(self, target_user, action):
        protected_actions = ["update", "delete", "lock", "unlock"]
        if (
            action in protected_actions
            and target_user.is_superuser
            and not self.request.user.is_superuser
        ):
            return (
                "Only a superadmin can manage another superadmin.",
                status.HTTP_403_FORBIDDEN,
            )

        if action in ["delete", "lock"] and target_user.id == self.request.user.id:
            return (
                f"A superadmin cannot {action} themselves.",
                status.HTTP_400_BAD_REQUEST,
            )
        return None

    @extend_schema(
        operation_id="admin_user_list",
        summary="List admin users",
        description=(
            "Returns admin dashboard users. Requires `admin_users.list` or `admin_users` permission."
        ),
        responses={
            200: OpenApiResponse(
                response=AdminUserListResponseSerializer,
                description="Admin user list retrieved successfully.",
            ),
            403: OpenApiResponse(description="Admin dashboard permission required."),
        },
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_user_create",
        summary="Create admin user",
        description=(
            "Creates an admin dashboard user with a default password. "
            "`is_superadmin=true` creates another superadmin; otherwise permissions control dashboard visibility."
        ),
        request=AdminUserCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=AdminUserCreateResponseSerializer,
                description="Admin user created successfully.",
            ),
            400: OpenApiResponse(description="Admin user validation failed."),
            403: OpenApiResponse(description="Admin dashboard permission required."),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get("is_superadmin") is True and not request.user.is_superuser:
            return Response(
                {
                    "success": False,
                    "detail": "Only a superadmin can create another superadmin.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user = serializer.save()
        self.log_admin_action(
            NotifyLogAction.CREATE,
            user,
            "Admin user created.",
            {"target_email": user.email, "is_superadmin": user.is_superuser},
        )
        return Response(
            {
                "success": True,
                "message": "Admin user created successfully.",
                "data": self.serialize_admin_user(user),
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="admin_user_retrieve",
        summary="Retrieve admin user",
        description=(
            "Returns details for one admin dashboard user by ID. Requires `admin_users.list` or `admin_users` permission."
        ),
        responses={
            200: OpenApiResponse(
                response=AdminUserRetrieveResponseSerializer,
                description="Admin user details retrieved successfully.",
            ),
            403: OpenApiResponse(description="Admin dashboard permission required."),
            404: OpenApiResponse(description="Admin user not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        access_error = self.get_target_access_error(instance, "retrieve")
        if access_error:
            message, response_status = access_error
            return Response(
                {"success": False, "detail": message},
                status=response_status,
            )

        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_user_update",
        summary="Update admin user",
        description=(
            "Updates admin dashboard user details, permissions, superadmin status, or password."
        ),
        request=AdminUserUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=AdminUserUpdateResponseSerializer,
                description="Admin user updated successfully.",
            ),
            400: OpenApiResponse(description="Admin user validation failed."),
            403: OpenApiResponse(description="Super admin access required."),
            404: OpenApiResponse(description="Admin user not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        access_error = self.get_target_access_error(instance, "update")
        if access_error:
            message, response_status = access_error
            return Response(
                {"success": False, "detail": message},
                status=response_status,
            )

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get("is_superadmin") is True and not request.user.is_superuser:
            return Response(
                {
                    "success": False,
                    "detail": "Only a superadmin can grant superadmin access.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if instance.id == request.user.id and serializer.validated_data.get("is_superadmin") is False:
            return Response(
                {
                    "success": False,
                    "detail": "A superadmin cannot remove their own superadmin access.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        self.log_admin_action(
            NotifyLogAction.UPDATE,
            user,
            "Admin user updated.",
            {"target_email": user.email, "updated_fields": list(request.data.keys())},
        )
        return Response(
            {
                "success": True,
                "message": "Admin user updated successfully.",
                "data": self.serialize_admin_user(user),
            },
            status=status.HTTP_200_OK,
        )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(
        operation_id="admin_user_delete",
        summary="Delete admin user",
        description="Deletes an admin dashboard user. A superadmin cannot delete themselves.",
        responses={
            200: OpenApiResponse(
                response=AdminUserDeleteResponseSerializer,
                description="Admin user deleted successfully.",
            ),
            400: OpenApiResponse(description="A superadmin cannot delete themselves."),
            403: OpenApiResponse(description="Admin dashboard permission required."),
            404: OpenApiResponse(description="Admin user not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        access_error = self.get_target_access_error(instance, "delete")
        if access_error:
            message, response_status = access_error
            return Response(
                {"success": False, "detail": message},
                status=response_status,
            )

        target_email = instance.email
        target_is_superadmin = instance.is_superuser
        self.log_admin_action(
            NotifyLogAction.DELETE,
            instance,
            "Admin user deleted.",
            {"target_email": target_email, "is_superadmin": target_is_superadmin},
        )
        instance.delete()
        return Response(
            {
                "success": True,
                "message": "Admin user deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_user_bulk_delete",
        summary="Bulk delete admin users",
        description=(
            "Deletes selected admin dashboard users. Self-deletion is blocked, and non-superadmins "
            "cannot delete superadmins."
        ),
        request=AdminUserBulkDeleteSerializer,
        responses={
            200: OpenApiResponse(
                response=AdminUserBulkDeleteResponseSerializer,
                description="Bulk delete completed.",
            ),
            400: OpenApiResponse(description="Bulk delete validation failed."),
            403: OpenApiResponse(description="Admin dashboard permission required."),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = AdminUserBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        admin_user_ids = serializer.validated_data["admin_user_ids"]
        queryset = self.get_queryset().filter(id__in=admin_user_ids)
        found_ids = set(queryset.values_list("id", flat=True))
        skipped = [
            {"id": admin_user_id, "reason": "Admin user not found."}
            for admin_user_id in admin_user_ids
            if admin_user_id not in found_ids
        ]
        deleted_count = 0

        for target_user in queryset:
            access_error = self.get_target_access_error(target_user, "delete")
            if access_error:
                message, _ = access_error
                skipped.append({"id": target_user.id, "reason": message})
                continue

            target_email = target_user.email
            target_is_superadmin = target_user.is_superuser
            self.log_admin_action(
                NotifyLogAction.DELETE,
                target_user,
                "Admin user deleted in bulk.",
                {
                    "target_email": target_email,
                    "is_superadmin": target_is_superadmin,
                },
            )
            target_user.delete()
            deleted_count += 1

        return Response(
            {
                "success": True,
                "message": f"{deleted_count} admin user(s) deleted successfully.",
                "deleted_count": deleted_count,
                "skipped": skipped,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_user_lock",
        summary="Lock admin user",
        description="Locks an admin user out of the dashboard by setting `is_active=false`.",
        responses={
            200: OpenApiResponse(
                response=AdminUserAccessResponseSerializer,
                description="Admin user locked successfully.",
            ),
            400: OpenApiResponse(description="A superadmin cannot lock themselves."),
        },
    )
    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        instance = self.get_object()
        access_error = self.get_target_access_error(instance, "lock")
        if access_error:
            message, response_status = access_error
            return Response(
                {"success": False, "detail": message},
                status=response_status,
            )

        instance.is_active = False
        instance.status = UserStatus.BLOCKED
        instance.save(update_fields=["is_active", "status", "updated_at"])
        self.log_admin_action(
            NotifyLogAction.UPDATE,
            instance,
            "Admin user locked.",
            {"target_email": instance.email},
        )
        return Response(
            {
                "success": True,
                "message": "Admin user locked successfully.",
                "data": self.serialize_admin_user(instance),
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_user_unlock",
        summary="Unlock admin user",
        description="Restores admin dashboard access by setting `is_active=true`.",
        responses={
            200: OpenApiResponse(
                response=AdminUserAccessResponseSerializer,
                description="Admin user unlocked successfully.",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, pk=None):
        instance = self.get_object()
        access_error = self.get_target_access_error(instance, "unlock")
        if access_error:
            message, response_status = access_error
            return Response(
                {"success": False, "detail": message},
                status=response_status,
            )

        instance.is_active = True
        instance.status = UserStatus.ACTIVE
        instance.save(update_fields=["is_active", "status", "updated_at"])
        self.log_admin_action(
            NotifyLogAction.UPDATE,
            instance,
            "Admin user unlocked.",
            {"target_email": instance.email},
        )
        return Response(
            {
                "success": True,
                "message": "Admin user unlocked successfully.",
                "data": self.serialize_admin_user(instance),
            },
            status=status.HTTP_200_OK,
        )
