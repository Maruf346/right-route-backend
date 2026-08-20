from django.shortcuts import render
from core.permissions import IsAdminUserPermission
from core.permissions import HasAdminDashboardPermission
from rest_framework.permissions import IsAuthenticated
from core.viewsets import OwnModelViewSet, OwnReadOnlyModelViewSet
from .models import SubscriptionPlan, UserSubscription
from .serializers import *
from .filters import SubscriptionPlanFilterSet
from rest_framework.decorators import action
from subscription.services.purchase_service import SubscriptionPurchaseService
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets
from core.constants import PlanType, UserStatus, UserSubscriptionStatus, PaymentStatus, PURCHASE_PLATFORM
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema


@extend_schema(tags=["Admin - Subscription Plans"])
class SubscriptionPlanViewSet(OwnModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminUserPermission]
    queryset = SubscriptionPlan.objects.all()
    model = SubscriptionPlan
    delete_message = "Subscription Plan Deleted."
    filterset_class = SubscriptionPlanFilterSet


@extend_schema(tags=["Subscriptions - User"])
class UserSubscriptionViewSet(OwnReadOnlyModelViewSet):
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            UserSubscription.objects
            .select_related("plan", "team", "user")
            .filter(user=self.request.user)
            .order_by("-created_at")
        )
    
    def get_active_subscription(self, user):
        now = timezone.now()
        return (
            UserSubscription.objects
            .select_related("plan", "team")
            .filter(user=user)
            .filter(
                Q(
                    status__in=[
                        UserSubscriptionStatus.ACTIVE,
                        UserSubscriptionStatus.TRIAL,
                    ],
                    expires_at__gt=now,
                )
                |
                Q(
                    status=UserSubscriptionStatus.GRACE_PERIOD,
                    grace_period_until__gt=now,
                )
            )
            .order_by("-created_at")
            .first()
        )
    
    @action(detail=False, methods=["get"], url_path="current-plan")
    def current_plan(self, request, *args, **kwargs):
        subscription = self.get_active_subscription(request.user)
        if not subscription:
            return Response(
                {
                    "success": True,
                    "data": None,
                    "message": "No active subscription found."
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {
                "success": True,
                "data": UserSubscriptionSerializer(subscription).data
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=["delete"])
    def remove(self, request, *args, **kwargs):
        object = self.get_object()
        if object.status == UserSubscriptionStatus.ACTIVE and object.payment_status == PaymentStatus.PAID:
            return Response(
                {
                    "success": False,
                    "message": "This Subscription Plan is Active."
                }, status=status.HTTP_200_OK
            )
        object.delete()
        return Response(
            {
                "success": True,
                "message": "Remove/Delete Subscription Object."
            }, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["post"])
    def purchase(self, request, *args, **kwargs):
        serializer = PurchaseSubscriptionSerializer(data=request.data,context={"request": request})
        serializer.is_valid(raise_exception=True)
        plan = serializer.context["plan"]
        subscription = (
            SubscriptionPurchaseService.create_pending_subscription(
                user=request.user,
                plan=plan
            )
        )
        return Response(
            {
                "success": True,
                "message": "Subscription purchase initiated.",
                "data": UserSubscriptionSerializer(subscription).data
            },
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=["post"], url_path="purchase-verify")
    def purchase_verify(self, request, *args, **kwargs):
        serializer = VerifyPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        subscription_plan_uuid = data.get("subscription_plan_uuid")
        user = request.user
        
        subscription = UserSubscription.objects.get(uuid=subscription_plan_uuid)
        if subscription.status != UserSubscriptionStatus.PENDING:
            raise ValidationError({
                "detail": f"Your Subscription Status is {subscription.status}."
            })
        subscription.status = UserSubscriptionStatus.ACTIVE
        subscription.payment_status = PaymentStatus.PAID
        subscription.save()

        # if data["platform"] == PURCHASE_PLATFORM.ANDROID:
        #     # TODO:
        #     # Verify using Google Play Developer API
        #     pass
        # elif data["platform"] == PURCHASE_PLATFORM.IOS:
        #     # TODO:
        #     # Verify using App Store Server API
        #     pass
        return Response(
            {
                "success": True,
                "message": "Purchase verified successfully.",
                "subscription_status": "active",
                "data": UserSubscriptionSerializer(subscription).data
            },
            status=status.HTTP_200_OK,
        )


class AdminSubscriberBaseViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    http_method_names = ["get", "patch", "post", "delete", "head", "options"]
    serializer_class = AdminSubscriberSerializer
    update_serializer_class = AdminSubscriberUpdateSerializer
    plan_type = None
    required_admin_permission = None

    def get_required_admin_permissions(self):
        return self.required_admin_permission

    def get_queryset(self):
        queryset = (
            UserSubscription.objects
            .select_related("user", "plan", "team")
            .prefetch_related("purchase_info", "user__purchase_info")
            .filter(plan__plan_type=self.plan_type)
            .order_by("user__email")
        )
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(user__email__icontains=search)
        return queryset

    def get_serializer_class(self):
        if self.action == "partial_update":
            return self.update_serializer_class
        return self.serializer_class

    def get_response_serializer_class(self):
        return self.serializer_class

    def list_success_response(self):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_response_serializer_class()(queryset, many=True)
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve_success_response(self):
        instance = self.get_object()
        serializer = self.get_response_serializer_class()(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def partial_update_success_response(self, request):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        subscription = serializer.save()
        response_serializer = self.get_response_serializer_class()(subscription)
        return Response(
            {
                "success": True,
                "message": "Subscriber updated successfully.",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def set_locked_status(self, locked):
        subscription = self.get_object()
        user = subscription.user
        user.is_active = not locked
        user.status = UserStatus.BLOCKED if locked else UserStatus.ACTIVE
        user.save(update_fields=["is_active", "status", "updated_at"])
        response_serializer = self.get_response_serializer_class()(subscription)
        return Response(
            {
                "success": True,
                "message": (
                    "Subscriber locked successfully."
                    if locked
                    else "Subscriber unlocked successfully."
                ),
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        return self.set_locked_status(True)

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, pk=None):
        return self.set_locked_status(False)


@extend_schema(tags=["Admin - Subscribers - Single"])
class AdminSingleSubscriberViewSet(AdminSubscriberBaseViewSet):
    serializer_class = AdminSubscriberSerializer
    update_serializer_class = AdminSingleSubscriberUpdateSerializer
    plan_type = PlanType.INDIVIDUAL
    required_admin_permission = "user_accounts.single"

    @extend_schema(
        operation_id="admin_single_subscriber_list",
        summary="List single plan subscribers",
        parameters=[
            OpenApiParameter("search", str, description="Search by subscriber email."),
        ],
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberListResponseSerializer,
                description="Single plan subscribers retrieved successfully.",
            )
        },
    )
    def list(self, request, *args, **kwargs):
        return self.list_success_response()

    @extend_schema(
        operation_id="admin_single_subscriber_retrieve",
        summary="Retrieve single plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberRetrieveResponseSerializer,
                description="Single plan subscriber retrieved successfully.",
            )
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return self.retrieve_success_response()

    @extend_schema(
        operation_id="admin_single_subscriber_update",
        summary="Update single plan subscriber",
        request=AdminSingleSubscriberUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberUpdateResponseSerializer,
                description="Single plan subscriber updated successfully.",
            )
        },
    )
    def partial_update(self, request, *args, **kwargs):
        return self.partial_update_success_response(request)

    @extend_schema(
        operation_id="admin_single_subscriber_lock",
        summary="Lock single plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberAccessResponseSerializer,
                description="Single plan subscriber locked successfully.",
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        return super().lock(request, pk=pk)

    @extend_schema(
        operation_id="admin_single_subscriber_unlock",
        summary="Unlock single plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberAccessResponseSerializer,
                description="Single plan subscriber unlocked successfully.",
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, pk=None):
        return super().unlock(request, pk=pk)


@extend_schema(tags=["Admin - Subscribers - Teams"])
class AdminTeamSubscriberViewSet(AdminSubscriberBaseViewSet):
    serializer_class = AdminTeamSubscriberSerializer
    update_serializer_class = AdminTeamSubscriberUpdateSerializer
    plan_type = PlanType.TEAM
    required_admin_permission = "user_accounts.teams"

    def get_response_serializer_class(self):
        return AdminTeamSubscriberSerializer

    def set_locked_status(self, locked):
        subscription = self.get_object()
        affected_users = [subscription.user]
        if subscription.team:
            affected_users.extend(
                member.user
                for member in subscription.team.members.select_related("user").all()
            )

        for user in affected_users:
            user.is_active = not locked
            user.status = UserStatus.BLOCKED if locked else UserStatus.ACTIVE
            user.save(update_fields=["is_active", "status", "updated_at"])

        response_serializer = self.get_response_serializer_class()(subscription)
        return Response(
            {
                "success": True,
                "message": (
                    "Team subscriber and drivers locked successfully."
                    if locked
                    else "Team subscriber and drivers unlocked successfully."
                ),
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_team_subscriber_list",
        summary="List team plan subscribers",
        parameters=[
            OpenApiParameter("search", str, description="Search by subscriber email."),
        ],
        responses={
            200: OpenApiResponse(
                response=AdminTeamSubscriberListResponseSerializer,
                description="Team plan subscribers retrieved successfully.",
            )
        },
    )
    def list(self, request, *args, **kwargs):
        return self.list_success_response()

    @extend_schema(
        operation_id="admin_team_subscriber_retrieve",
        summary="Retrieve team plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminTeamSubscriberRetrieveResponseSerializer,
                description="Team plan subscriber retrieved successfully.",
            )
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return self.retrieve_success_response()

    @extend_schema(
        operation_id="admin_team_subscriber_update",
        summary="Update team plan subscriber",
        request=AdminTeamSubscriberUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=AdminTeamSubscriberUpdateResponseSerializer,
                description="Team plan subscriber updated successfully.",
            )
        },
    )
    def partial_update(self, request, *args, **kwargs):
        return self.partial_update_success_response(request)

    @extend_schema(
        operation_id="admin_team_subscriber_delete",
        summary="Delete team subscriber account",
        responses={
            200: OpenApiResponse(
                response=AdminSubscriberDeleteResponseSerializer,
                description="Team subscriber account deleted successfully.",
            )
        },
    )
    def destroy(self, request, *args, **kwargs):
        subscription = self.get_object()
        user = subscription.user
        user.delete()
        return Response(
            {
                "success": True,
                "message": "Team subscriber account deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="admin_team_subscriber_lock",
        summary="Lock team plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminTeamSubscriberAccessResponseSerializer,
                description="Team plan subscriber locked successfully.",
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        return super().lock(request, pk=pk)

    @extend_schema(
        operation_id="admin_team_subscriber_unlock",
        summary="Unlock team plan subscriber",
        responses={
            200: OpenApiResponse(
                response=AdminTeamSubscriberAccessResponseSerializer,
                description="Team plan subscriber unlocked successfully.",
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, pk=None):
        return super().unlock(request, pk=pk)


# class SubscriptionPlanPayActionView(APIView):
#     def get(self, request, *args, **kwargs):
#         subscription_plan_uuid = self.request.query_params.get("subscription-plan-uuid")
#         stripe_token = self.request.query_params.get("stripe-token")
#         subscription = UserSubscription.objects.get(uuid=subscription_plan_uuid, stripe_subscription_id=stripe_token)
#         if subscription.status != UserSubscriptionStatus.PENDING:
#             raise ValidationError({
#                 "detail": f"Your Subscription Status is {subscription.status}."
#             })
#         subscription.status = UserSubscriptionStatus.ACTIVE
#         subscription.payment_status = PaymentStatus.PAID
#         subscription.save()
#         return Response(
#             {
#                 "success": True,
#                 "detail": "Payment Successfully Complete!"
#             }
#         )


