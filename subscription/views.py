from django.shortcuts import render
from core.permissions import IsAdminUserPermission
from rest_framework.permissions import IsAuthenticated
from core.viewsets import OwnModelViewSet, OwnReadOnlyModelViewSet
from .models import SubscriptionPlan, UserSubscription
from .serializers import SubscriptionPlanSerializer, UserSubscriptionSerializer, PurchaseSubscriptionSerializer, VerifyPurchaseSerializer
from .filters import SubscriptionPlanFilterSet
from rest_framework.decorators import action
from subscription.services.purchase_service import SubscriptionPurchaseService
from rest_framework.response import Response
from rest_framework import status
from core.constants import UserSubscriptionStatus, PaymentStatus, PURCHASE_PLATFORM
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q


class SubscriptionPlanViewSet(OwnModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminUserPermission]
    queryset = SubscriptionPlan.objects.all()
    model = SubscriptionPlan
    delete_message = "Subscription Plan Deleted."
    filterset_class = SubscriptionPlanFilterSet


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


