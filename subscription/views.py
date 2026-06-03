from django.shortcuts import render
from core.permissions import IsAdminUserPermission
from rest_framework.permissions import IsAuthenticated
from core.viewsets import OwnModelViewSet, OwnReadOnlyModelViewSet
from .models import SubscriptionPlan, UserSubscription
from .serializers import SubscriptionPlanSerializer, UserSubscriptionSerializer, PurchaseSubscriptionSerializer
from .filters import SubscriptionPlanFilterSet
from rest_framework.decorators import action
from subscription.services.purchase_service import SubscriptionPurchaseService
from rest_framework.response import Response
from rest_framework import status
from core.constants import UserSubscriptionStatus, PaymentStatus
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.exceptions import ValidationError
import uuid
from account.models import Team

class SubscriptionPlanViewSet(OwnModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminUserPermission]
    queryset = SubscriptionPlan.objects.all().order_by("-created_at")
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

    def create_stripe_token(self, subscription):
        unique_id = uuid.uuid4().hex
        return unique_id
    
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
        subscription.stripe_subscription_id=self.create_stripe_token(subscription)
        subscription.save()
        
        generate_payment_url = f"http://127.0.0.1:8003/purchase/pay/for/subscription/?stripe-token={subscription.stripe_subscription_id}&subscription-plan-uuid={subscription.uuid}"
        return Response(
            {
                "success": True,
                "message": "Subscription purchase initiated.",
                "data": {
                    "subscription_object": UserSubscriptionSerializer(subscription).data,
                    "payment-url": generate_payment_url
                }
            },
            status=status.HTTP_201_CREATED
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

class SubscriptionPlanPayActionView(APIView):
    def get(self, request, *args, **kwargs):
        subscription_plan_uuid = self.request.query_params.get("subscription-plan-uuid")
        stripe_token = self.request.query_params.get("stripe-token")
        subscription = UserSubscription.objects.get(
            uuid=subscription_plan_uuid,
            stripe_subscription_id=stripe_token
        )
        if subscription.status != UserSubscriptionStatus.PENDING:
            raise ValidationError({
                "detail": f"Your Subscription Status is {subscription.status}."
            })
        subscription.status = UserSubscriptionStatus.ACTIVE
        subscription.payment_status = PaymentStatus.PAID
        subscription.save()
        return Response(
            {
                "success": True,
                "detail": "Payment Successfully Complete!"
            }
        )


