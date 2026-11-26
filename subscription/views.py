import base64
from datetime import datetime, time, timedelta
from decimal import Decimal
import json
import logging

from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from core.permissions import IsAdminUserPermission
from core.permissions import HasAdminDashboardPermission
from rest_framework.permissions import AllowAny, IsAuthenticated
from core.viewsets import OwnModelViewSet, OwnReadOnlyModelViewSet
from .models import (
    CouponRedemption,
    DiscountCoupon,
    FleetAccount,
    PurchaseInfo,
    SubscriptionPlan,
    UserSubscription,
)
from .serializers import *
from .filters import SubscriptionPlanFilterSet
from rest_framework.decorators import action
from subscription.services.google_play import GooglePlayBillingService
from subscription.services.purchase_service import SubscriptionPurchaseService
from subscription.services.stripe_service import (
    activate_web_subscription_from_checkout,
    create_web_checkout_session,
    get_or_create_fleet_plan,
    is_stripe_configured,
    process_stripe_webhook_event,
    sync_coupon_to_stripe,
    sync_fleet_to_stripe,
)
from account.emailsend import EmailFleetOwnerWelcome, EmailSingleSubscriberWelcome
from account.models import Team, User
from team_dashboard.utils import generate_secure_password
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets
from core.constants import (
    BillingType,
    NotifyLogAction,
    PlanType,
    UserStatus,
    UserSubscriptionStatus,
    UserType,
    PaymentStatus,
    PURCHASE_PLATFORM,
    PURCHASE_VERIFY_STATUS,
)
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.utils import timezone
from django.db.models import Q, Sum
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from notification.utils import log_activity
from subscription.services.purchase_verify import create_or_update_purchase_info

logger = logging.getLogger(__name__)


@extend_schema(tags=["Subscription Plans - Admin"])
class SubscriptionPlanViewSet(OwnModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminUserPermission]
    queryset = SubscriptionPlan.objects.all()
    model = SubscriptionPlan
    delete_message = "Subscription Plan Deleted."
    filterset_class = SubscriptionPlanFilterSet

    def create_success_response(self, serializer):
        response = super().create_success_response(serializer)
        plan = serializer.instance
        log_activity(
            self.request,
            NotifyLogAction.CREATE,
            plan,
            "Subscription plan created.",
            {"plan_name": plan.name, "plan_type": plan.plan_type, "price": str(plan.price)},
        )
        return response

    def update_success_response(self, serializer):
        response = super().update_success_response(serializer)
        plan = serializer.instance
        log_activity(
            self.request,
            NotifyLogAction.UPDATE,
            plan,
            "Subscription plan updated.",
            {"plan_name": plan.name, "updated_fields": list(self.request.data.keys())},
        )
        return response

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        metadata = {"plan_name": instance.name, "plan_type": instance.plan_type, "price": str(instance.price)}
        response = super().destroy(request, *args, **kwargs)
        if response.status_code < 400:
            log_activity(request, NotifyLogAction.DELETE, instance, "Subscription plan deleted.", metadata)
        return response


@extend_schema(tags=["Subscriptions - User"])
class UserSubscriptionViewSet(OwnReadOnlyModelViewSet):
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Avoid accessing request.user during schema introspection
        if getattr(self, "swagger_fake_view", False):
            return UserSubscription.objects.none()

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

    @extend_schema(
        operation_id="subscription_purchase_create",
        summary="Create pending subscription before app-store checkout",
        request=PurchaseSubscriptionSerializer,
        responses={201: PurchaseSubscriptionResponseSerializer},
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
    
    def _ensure_purchase_ownership(self, *, user, transaction_id, purchase_token):
        if transaction_id:
            existing_tx = (
                PurchaseInfo.objects.filter(transaction_id=transaction_id)
                .exclude(user=user)
                .first()
            )
            if existing_tx:
                raise ValidationError({"transaction_id": "This purchase is already linked to another account."})

        if purchase_token:
            existing_token = (
                PurchaseInfo.objects.filter(purchase_token=purchase_token)
                .exclude(user=user)
                .first()
            )
            if existing_token:
                raise ValidationError({"purchase_token": "This Google Play purchase is already linked to another account."})

    def _activate_verified_subscription(
        self,
        *,
        user,
        subscription,
        platform,
        product_id,
        transaction_id,
        original_transaction_id=None,
        purchase_token=None,
        receipt_data=None,
        package_name=None,
        order_id=None,
        amount=None,
        currency="USD",
        purchase_time=None,
        expiry_time=None,
        auto_renew=False,
        raw_response=None,
    ):
        self._ensure_purchase_ownership(
            user=user,
            transaction_id=transaction_id,
            purchase_token=purchase_token,
        )

        verification_status = PURCHASE_VERIFY_STATUS.VERIFIED
        sub_status = UserSubscriptionStatus.ACTIVE
        merged_raw = dict(raw_response or {})

        if platform == PURCHASE_PLATFORM.ANDROID:
            verified_data = GooglePlayBillingService.verify_purchase(
                product_id=product_id,
                purchase_token=purchase_token or "",
                transaction_id=transaction_id,
                package_name=package_name,
                trial_days=getattr(subscription.plan, "trial_days", 7),
                fallback_expiry=expiry_time or subscription.expires_at,
                developer_payload=f"user:{user.id}|sub:{subscription.uuid}",
            )
            verification_status = verified_data["verification_status"]
            sub_status = verified_data["subscription_status"]
            purchase_time = verified_data["purchase_time"]
            expiry_time = verified_data["expiry_time"]
            auto_renew = verified_data["auto_renew"]
            order_id = verified_data.get("order_id") or order_id
            package_name = verified_data.get("package_name") or package_name
            merged_raw = {**merged_raw, **verified_data.get("raw_response", {})}

        purchase_time = purchase_time or timezone.now()
        expiry_time = expiry_time or subscription.expires_at
        amount = amount if amount is not None else subscription.plan.price
        currency = currency or subscription.plan.currency or "USD"
        original_transaction_id = original_transaction_id or transaction_id
        now = timezone.now()
        was_welcome_sent = (
            bool(subscription.welcome_email_sent_at)
            or UserSubscription.objects.filter(
                user=user,
                plan__plan_type=PlanType.INDIVIDUAL,
                welcome_email_sent_at__isnull=False,
            ).exists()
        )

        with transaction.atomic():
            # Supersede any prior active/trial/grace subscriptions on upgrade/downgrade/restore
            UserSubscription.objects.filter(
                user=user,
                status__in=[
                    UserSubscriptionStatus.ACTIVE,
                    UserSubscriptionStatus.TRIAL,
                    UserSubscriptionStatus.GRACE_PERIOD,
                ],
            ).exclude(id=subscription.id).update(
                status=UserSubscriptionStatus.CANCELLED,
                cancelled_at=now,
                auto_renew=False,
            )

            # Avoid UNIQUE constraint collision when re-verifying or restoring the same transaction_id
            if transaction_id:
                UserSubscription.objects.filter(
                    user=user,
                    latest_transaction_id=transaction_id,
                ).exclude(id=subscription.id).update(latest_transaction_id=None)

            team = subscription.team
            if subscription.plan.plan_type == PlanType.TEAM:
                team = getattr(user, "owned_team", None) or team
                if not team:
                    team_prefix = (user.email or f"user-{user.id}").split("@")[0]
                    team, _ = Team.objects.get_or_create(
                        owner=user,
                        defaults={
                            "name": f"{team_prefix}'s Team",
                            "max_members": subscription.plan.team_limit or 0,
                        },
                    )
                if subscription.plan.team_limit:
                    team.max_members = subscription.plan.team_limit
                    team.save(update_fields=["max_members"])

            subscription.team = team
            subscription.status = sub_status
            subscription.payment_status = PaymentStatus.PAID
            subscription.auto_renew = auto_renew
            subscription.last_renew_at = purchase_time
            subscription.expires_at = expiry_time
            subscription.original_transaction_id = original_transaction_id
            subscription.latest_transaction_id = transaction_id
            subscription.save(update_fields=[
                "team",
                "status",
                "payment_status",
                "auto_renew",
                "last_renew_at",
                "expires_at",
                "original_transaction_id",
                "latest_transaction_id",
                "updated_at",
            ])

            purchase_info, _ = create_or_update_purchase_info(
                user=user,
                subscription=subscription,
                platform=platform,
                product_id=product_id,
                transaction_id=transaction_id,
                original_transaction_id=original_transaction_id,
                purchase_token=purchase_token,
                receipt_data=receipt_data,
                package_name=package_name,
                order_id=order_id,
                amount=amount,
                currency=currency,
                purchase_time=purchase_time,
                expiry_time=expiry_time,
                auto_renew=auto_renew,
                verification_status=verification_status,
                raw_response=merged_raw,
            )

        if subscription.plan.plan_type == PlanType.INDIVIDUAL and not was_welcome_sent:
            try:
                EmailSingleSubscriberWelcome(user)
                subscription.welcome_email_sent_at = timezone.now()
                subscription.save(update_fields=["welcome_email_sent_at", "updated_at"])
            except Exception as exc:
                logger.warning("Failed sending single welcome email to %s: %s", user.email, exc)

        return subscription, purchase_info

    @extend_schema(
        operation_id="subscription_purchase_verify",
        summary="Record app-store purchase and activate subscription",
        request=VerifyPurchaseSerializer,
        responses={200: VerifyPurchaseResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="purchase-verify")
    def purchase_verify(self, request, *args, **kwargs):
        serializer = VerifyPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        subscription = UserSubscription.objects.select_related("plan", "team").filter(
            uuid=data.get("subscription_plan_uuid"),
            user=user,
        ).first()
        if not subscription:
            raise ValidationError({"detail": "Subscription not found for this user."})

        product_id = data["product_id"]
        if subscription.plan.product_id and subscription.plan.product_id != product_id:
            raise ValidationError({"product_id": "Product ID does not match this subscription plan."})

        subscription, purchase_info = self._activate_verified_subscription(
            user=user,
            subscription=subscription,
            platform=data["platform"],
            product_id=product_id,
            transaction_id=data["transaction_id"],
            original_transaction_id=data.get("original_transaction_id"),
            purchase_token=data.get("purchase_token"),
            receipt_data=data.get("receipt_data"),
            package_name=data.get("package_name"),
            order_id=data.get("order_id"),
            amount=data.get("amount"),
            currency=data.get("currency", "USD"),
            purchase_time=data.get("purchase_time"),
            expiry_time=data.get("expiry_time"),
            auto_renew=data.get("auto_renew", False),
            raw_response=data.get("raw_response"),
        )

        return Response(
            {
                "success": True,
                "message": "Purchase verified and subscription activated successfully.",
                "subscription_status": subscription.status.lower(),
                "purchase_id": purchase_info.id,
                "transaction_id": purchase_info.transaction_id,
                "verification_status": purchase_info.verification_status,
                "data": UserSubscriptionSerializer(subscription).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="subscription_restore",
        summary="Restore active Google Play or App Store purchases",
        request=RestorePurchasesSerializer,
        responses={200: RestorePurchasesResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="restore")
    def restore(self, request, *args, **kwargs):
        serializer = RestorePurchasesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        platform = serializer.validated_data["platform"]
        purchases = serializer.validated_data.get("purchases") or []
        user = request.user

        restored_sub = None
        last_error = None

        for item in purchases:
            product_id = item["product_id"]
            plan = SubscriptionPlan.objects.filter(product_id=product_id, is_active=True).first()
            if not plan:
                continue

            tx_id = (
                item.get("transaction_id")
                or item.get("order_id")
                or (f"gp_restore_{(item.get('purchase_token') or '')[:32]}")
            )
            purchase_token = item.get("purchase_token")
            if platform == PURCHASE_PLATFORM.ANDROID and not purchase_token:
                continue

            # Re-use existing subscription for the same purchase_token/tx if this user already holds it
            existing_pi = (
                PurchaseInfo.objects.select_related("subscription", "subscription__plan", "subscription__team")
                .filter(user=user)
                .filter(
                    Q(purchase_token=purchase_token) if purchase_token else Q(transaction_id=tx_id)
                )
                .order_by("-created_at")
                .first()
            )
            target_sub = existing_pi.subscription if (existing_pi and existing_pi.subscription and existing_pi.subscription.plan_id == plan.id) else None

            if not target_sub:
                now = timezone.now()
                team = getattr(user, "owned_team", None) if plan.plan_type == PlanType.TEAM else None
                target_sub = UserSubscription.objects.create(
                    user=user,
                    team=team,
                    plan=plan,
                    status=UserSubscriptionStatus.PENDING,
                    starts_at=now,
                    last_renew_at=now,
                    expires_at=now + SubscriptionPurchaseService.get_plan_duration(plan),
                    payment_status=PaymentStatus.PENDING,
                )

            try:
                restored_sub, _ = self._activate_verified_subscription(
                    user=user,
                    subscription=target_sub,
                    platform=platform,
                    product_id=product_id,
                    transaction_id=tx_id,
                    original_transaction_id=item.get("original_transaction_id") or tx_id,
                    purchase_token=purchase_token,
                    receipt_data=item.get("receipt_data"),
                    package_name=item.get("package_name"),
                    order_id=item.get("order_id"),
                    purchase_time=item.get("purchase_time"),
                    expiry_time=item.get("expiry_time"),
                    auto_renew=item.get("auto_renew", True),
                    raw_response=item.get("raw_response"),
                )
                break
            except ValidationError as exc:
                last_error = exc
                if target_sub.status == UserSubscriptionStatus.PENDING:
                    target_sub.delete()
                continue

        if not restored_sub:
            restored_sub = self.get_active_subscription(user)

        if not restored_sub:
            return Response(
                {
                    "success": True,
                    "restored": False,
                    "message": "No active subscription found to restore." if not last_error else "Unable to restore subscription.",
                    "data": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "success": True,
                "restored": True,
                "message": "Subscription restored successfully.",
                "data": UserSubscriptionSerializer(restored_sub).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="subscription_google_play_rtdn",
        summary="Receive Google Play Real-Time Developer Notifications (Pub/Sub webhook)",
        request=GooglePlayRTDNSerializer,
    )
    @action(detail=False, methods=["post"], url_path="google-play-rtdn", permission_classes=[AllowAny])
    def google_play_rtdn(self, request, *args, **kwargs):
        message = (request.data or {}).get("message") or {}
        raw_b64 = message.get("data")
        if not raw_b64:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        try:
            decoded = json.loads(base64.b64decode(raw_b64).decode("utf-8"))
        except Exception:
            return Response({"status": "invalid_payload"}, status=status.HTTP_400_BAD_REQUEST)

        sub_notif = decoded.get("subscriptionNotification") or {}
        purchase_token = sub_notif.get("purchaseToken")
        notif_type = sub_notif.get("notificationType")
        package_name = decoded.get("packageName") or GooglePlayBillingService.get_package_name()

        if not purchase_token:
            return Response({"status": "no_token"}, status=status.HTTP_200_OK)

        purchase_info = (
            PurchaseInfo.objects.select_related("subscription", "subscription__plan", "user")
            .filter(purchase_token=purchase_token)
            .order_by("-created_at")
            .first()
        )
        if not purchase_info or not purchase_info.subscription:
            logger.info("RTDN received for unknown purchase_token (type=%s)", notif_type)
            return Response({"status": "unknown_token"}, status=status.HTTP_200_OK)

        sub = purchase_info.subscription
        # Revoked / Expired notifications immediately revoke access if Play API unavailable or confirms
        if notif_type in (12, 13):  # REVOKED=12, EXPIRED=13
            sub.status = UserSubscriptionStatus.EXPIRED
            sub.auto_renew = False
            sub.save(update_fields=["status", "auto_renew", "updated_at"])
            return Response({"status": "expired"}, status=status.HTTP_200_OK)

        if notif_type == 3:  # SUBSCRIPTION_CANCELED
            sub.auto_renew = False
            sub.cancelled_at = timezone.now()
            sub.save(update_fields=["auto_renew", "cancelled_at", "updated_at"])

        if GooglePlayBillingService.has_credentials():
            try:
                verified = GooglePlayBillingService.verify_purchase(
                    product_id=purchase_info.product_id or sub.plan.product_id,
                    purchase_token=purchase_token,
                    package_name=package_name,
                    trial_days=getattr(sub.plan, "trial_days", 7),
                    fallback_expiry=sub.expires_at,
                )
                sub.status = verified["subscription_status"]
                sub.expires_at = verified["expiry_time"]
                sub.auto_renew = verified["auto_renew"]
                sub.last_renew_at = timezone.now()
                sub.save(update_fields=["status", "expires_at", "auto_renew", "last_renew_at", "updated_at"])
            except ValidationError:
                sub.status = UserSubscriptionStatus.EXPIRED
                sub.auto_renew = False
                sub.save(update_fields=["status", "auto_renew", "updated_at"])

        return Response({"status": "processed"}, status=status.HTTP_200_OK)


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
        log_activity(
            request,
            NotifyLogAction.UPDATE,
            subscription,
            "Subscriber updated.",
            {
                "subscriber_email": subscription.user.email,
                "plan_type": self.plan_type,
                "updated_fields": list(request.data.keys()),
            },
        )
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
        log_activity(
            self.request,
            NotifyLogAction.UPDATE,
            subscription,
            "Subscriber locked." if locked else "Subscriber unlocked.",
            {"subscriber_email": user.email, "plan_type": self.plan_type, "locked": locked},
        )
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


@extend_schema(tags=["Subscribers - Single - Admin"])
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


@extend_schema(tags=["Subscribers - Teams - Admin"])
class AdminTeamSubscriberViewSet(AdminSubscriberBaseViewSet):
    serializer_class = AdminTeamSubscriberSerializer
    update_serializer_class = AdminTeamSubscriberUpdateSerializer
    plan_type = PlanType.TEAM
    required_admin_permission = "user_accounts.teams"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(plan__product_id="rr_fleet_custom")
            .filter(user__fleet_account__isnull=True)
        )

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

        log_activity(
            self.request,
            NotifyLogAction.UPDATE,
            subscription,
            "Team subscriber locked." if locked else "Team subscriber unlocked.",
            {
                "subscriber_email": subscription.user.email,
                "team_id": subscription.team_id,
                "affected_user_count": len(affected_users),
                "locked": locked,
            },
        )
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
        metadata = {
            "subscriber_email": user.email,
            "subscription_id": subscription.id,
            "team_id": subscription.team_id,
        }
        log_activity(request, NotifyLogAction.DELETE, subscription, "Team subscriber account deleted.", metadata)
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


@extend_schema(tags=["Subscribers - Fleets - Admin"])
class AdminFleetAccountViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "user_accounts.fleet"
    serializer_class = FleetAccountSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_required_admin_permissions(self):
        return self.required_admin_permission

    def get_queryset(self):
        queryset = (
            FleetAccount.objects
            .select_related("user", "team", "subscription", "subscription__plan")
            .order_by("-created_at")
        )
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search)
                | Q(company_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(phone__icontains=search)
            )
        from_date = self.request.query_params.get("from_date")
        if from_date:
            queryset = queryset.filter(sign_up_date__gte=from_date)
        to_date = self.request.query_params.get("to_date")
        if to_date:
            queryset = queryset.filter(sign_up_date__lte=to_date)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = FleetAccountSerializer(queryset, many=True)
        total_drivers = queryset.aggregate(total=Sum("driver_allowance"))["total"] or 0
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "total_drivers": total_drivers,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, **kwargs):
        fleet = self.get_object()
        return Response(
            {"success": True, "data": FleetAccountSerializer(fleet).data},
            status=status.HTTP_200_OK,
        )

    def create(self, request, *args, **kwargs):
        serializer = FleetAccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if not full_name:
            raise ValidationError({"full_name": "First/Last Name is required."})
        if not email:
            raise ValidationError({"email": "Email is required."})

        raw_password = data.get("password") or generate_secure_password(12)
        sign_up_date = data.get("sign_up_date") or timezone.localdate()
        billing_type = data.get("billing_type") or BillingType.MONTHLY
        next_payment_date = data.get("next_payment_date")
        if not next_payment_date:
            next_payment_date = sign_up_date + timedelta(
                days=365 if billing_type == BillingType.YEARLY else 30
            )

        driver_allowance = data.get("driver_allowance") or 100
        company_name = (data.get("company_name") or "").strip()
        team_name = company_name or f"{full_name}'s Fleet"
        sub_status = data.get("status") or UserSubscriptionStatus.ACTIVE

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=raw_password,
                user_type=UserType.MAIN_USER,
                status=UserStatus.ACTIVE,
                is_active=True,
                is_email_verified=True,
            )
            team, _ = Team.objects.get_or_create(
                owner=user,
                defaults={"name": team_name, "max_members": driver_allowance, "is_active": True},
            )
            team.name = team_name
            team.max_members = driver_allowance
            team.is_active = True
            team.save(update_fields=["name", "max_members", "is_active", "updated_at"])

            fleet_plan = get_or_create_fleet_plan()
            starts_dt = timezone.make_aware(datetime.combine(sign_up_date, time(hour=0, minute=0)))
            expires_dt = timezone.make_aware(datetime.combine(next_payment_date, time(hour=23, minute=59)))

            subscription = UserSubscription.objects.create(
                user=user,
                team=team,
                plan=fleet_plan,
                status=sub_status,
                starts_at=starts_dt,
                last_renew_at=starts_dt,
                expires_at=expires_dt,
                auto_renew=True,
                payment_status=PaymentStatus.PAID,
                discount_period=data.get("discount_period", "0") or "0",
                discount_amount=data.get("discount_amount", "0") or "0",
                state=data.get("state", ""),
                notes=data.get("notes", ""),
            )

            fleet = FleetAccount.objects.create(
                user=user,
                team=team,
                subscription=subscription,
                full_name=full_name,
                company_name=company_name,
                phone=data.get("phone", ""),
                sign_up_date=sign_up_date,
                next_payment_date=next_payment_date,
                driver_allowance=driver_allowance,
                price=data.get("price", Decimal("0.00")),
                billing_type=billing_type,
                discount_period=data.get("discount_period", "0") or "0",
                discount_amount=data.get("discount_amount", "0") or "0",
                state=data.get("state", ""),
                platform=data.get("platform", "Stripe") or "Stripe",
                notes=data.get("notes", ""),
                status=sub_status,
            )

        sync_fleet_to_stripe(fleet)
        log_activity(
            request,
            NotifyLogAction.CREATE,
            fleet,
            "Fleet account created.",
            {"fleet_email": email, "company_name": company_name, "driver_allowance": driver_allowance},
        )
        return Response(
            {
                "success": True,
                "message": "Fleet account created successfully.",
                "data": FleetAccountSerializer(fleet).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        fleet = self.get_object()
        serializer = FleetAccountWriteSerializer(instance=fleet, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            user = fleet.user
            user_dirty = []
            if "email" in data and data["email"] != user.email:
                user.email = data["email"]
                user_dirty.append("email")
            if data.get("password"):
                user.set_password(data["password"])
                user_dirty.append("password")
            if user_dirty:
                user.save(update_fields=[*user_dirty, "updated_at"])

            for field in (
                "full_name",
                "company_name",
                "phone",
                "sign_up_date",
                "next_payment_date",
                "driver_allowance",
                "price",
                "billing_type",
                "discount_period",
                "discount_amount",
                "state",
                "platform",
                "notes",
                "status",
            ):
                if field in data:
                    setattr(fleet, field, data[field])
            fleet.save()

            team = fleet.team
            team.name = fleet.company_name or f"{fleet.full_name}'s Fleet"
            team.max_members = fleet.driver_allowance
            team.save(update_fields=["name", "max_members", "updated_at"])

            if fleet.subscription:
                sub = fleet.subscription
                sub.status = fleet.status
                sub.discount_period = fleet.discount_period
                sub.discount_amount = fleet.discount_amount
                sub.state = fleet.state
                sub.notes = fleet.notes
                if fleet.next_payment_date:
                    sub.expires_at = timezone.make_aware(
                        datetime.combine(fleet.next_payment_date, time(hour=23, minute=59))
                    )
                sub.save()

        if fleet.stripe_sync_status != "SYNCED" or any(
            k in data for k in ("email", "company_name", "full_name", "phone", "price", "billing_type", "next_payment_date")
        ):
            sync_fleet_to_stripe(fleet)

        log_activity(
            request,
            NotifyLogAction.UPDATE,
            fleet,
            "Fleet account updated.",
            {"fleet_email": fleet.user.email, "updated_fields": list(request.data.keys())},
        )
        return Response(
            {
                "success": True,
                "message": "Fleet account updated successfully.",
                "data": FleetAccountSerializer(fleet).data,
            },
            status=status.HTTP_200_OK,
        )

    def destroy(self, request, *args, **kwargs):
        fleet = self.get_object()
        user = fleet.user
        metadata = {"fleet_email": user.email, "company_name": fleet.company_name, "fleet_id": fleet.id}
        log_activity(request, NotifyLogAction.DELETE, fleet, "Fleet account deleted.", metadata)
        user.delete()
        return Response(
            {"success": True, "message": "Fleet account deleted successfully."},
            status=status.HTTP_200_OK,
        )

    def _set_locked(self, request, locked):
        fleet = self.get_object()
        affected_users = [fleet.user]
        if fleet.team:
            affected_users.extend(
                member.user for member in fleet.team.members.select_related("user").all()
            )
        for u in affected_users:
            u.is_active = not locked
            u.status = UserStatus.BLOCKED if locked else UserStatus.ACTIVE
            u.save(update_fields=["is_active", "status", "updated_at"])

        log_activity(
            request,
            NotifyLogAction.UPDATE,
            fleet,
            "Fleet account locked." if locked else "Fleet account unlocked.",
            {"fleet_email": fleet.user.email, "locked": locked, "affected_user_count": len(affected_users)},
        )
        return Response(
            {
                "success": True,
                "message": "Fleet account and drivers locked successfully." if locked else "Fleet account and drivers unlocked successfully.",
                "data": FleetAccountSerializer(fleet).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        return self._set_locked(request, True)

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, pk=None):
        return self._set_locked(request, False)

    @action(detail=True, methods=["post"], url_path="send-welcome-email")
    def send_welcome_email(self, request, pk=None):
        fleet = self.get_object()
        serializer = FleetWelcomeEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data.get("password") or None

        try:
            EmailFleetOwnerWelcome(
                fleet.user,
                full_name=fleet.full_name,
                password=password,
            )
        except Exception as exc:
            raise ValidationError({"detail": f"Unable to send welcome email: {str(exc)}"})

        fleet.welcome_email_sent_at = timezone.now()
        fleet.save(update_fields=["welcome_email_sent_at", "updated_at"])
        log_activity(
            request,
            NotifyLogAction.UPDATE,
            fleet,
            "Fleet owner welcome email sent.",
            {"fleet_email": fleet.user.email},
        )
        return Response(
            {
                "success": True,
                "message": f"Welcome email sent to {fleet.user.email}.",
                "data": FleetAccountSerializer(fleet).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="sync-stripe")
    def sync_stripe(self, request, pk=None):
        fleet = self.get_object()
        sync_fleet_to_stripe(fleet)
        return Response(
            {
                "success": True,
                "message": f"Stripe sync status: {fleet.stripe_sync_status}",
                "data": FleetAccountSerializer(fleet).data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Coupons - Admin"])
class AdminDiscountCouponViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "discount_codes.manage"
    serializer_class = DiscountCouponSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_required_admin_permissions(self):
        return self.required_admin_permission

    def get_queryset(self):
        queryset = DiscountCoupon.objects.select_related("created_by").all()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(description__icontains=search))
        scope = self.request.query_params.get("applicable_plan_type")
        if scope:
            queryset = queryset.filter(applicable_plan_type=scope.upper())
        active = self.request.query_params.get("is_active")
        if active is not None and active != "":
            queryset = queryset.filter(is_active=active.lower() in ("true", "1", "yes"))
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = DiscountCouponSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": queryset.count(), "data": serializer.data},
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, **kwargs):
        return Response(
            {"success": True, "data": DiscountCouponSerializer(self.get_object()).data},
            status=status.HTTP_200_OK,
        )

    def create(self, request, *args, **kwargs):
        serializer = DiscountCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupon = serializer.save(created_by=request.user)
        sync_coupon_to_stripe(coupon)
        log_activity(
            request,
            NotifyLogAction.CREATE,
            coupon,
            "Discount coupon created.",
            {"code": coupon.code, "scope": coupon.applicable_plan_type},
        )
        return Response(
            {"success": True, "message": "Coupon created successfully.", "data": DiscountCouponSerializer(coupon).data},
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = DiscountCouponSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        coupon = serializer.save()
        sync_coupon_to_stripe(coupon)
        log_activity(
            request,
            NotifyLogAction.UPDATE,
            coupon,
            "Discount coupon updated.",
            {"code": coupon.code, "updated_fields": list(request.data.keys())},
        )
        return Response(
            {"success": True, "message": "Coupon updated successfully.", "data": DiscountCouponSerializer(coupon).data},
            status=status.HTTP_200_OK,
        )

    def destroy(self, request, *args, **kwargs):
        coupon = self.get_object()
        code = coupon.code
        log_activity(request, NotifyLogAction.DELETE, coupon, "Discount coupon deleted.", {"code": code})
        coupon.delete()
        return Response({"success": True, "message": f"Coupon {code} deleted."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="toggle-active")
    def toggle_active(self, request, pk=None):
        coupon = self.get_object()
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=["is_active", "updated_at"])
        sync_coupon_to_stripe(coupon)
        return Response(
            {
                "success": True,
                "message": f"Coupon {coupon.code} {'activated' if coupon.is_active else 'deactivated'}.",
                "data": DiscountCouponSerializer(coupon).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="redemptions")
    def redemptions(self, request, pk=None):
        coupon = self.get_object()
        items = coupon.redemptions.select_related("user", "plan").all()
        return Response(
            {"success": True, "count": items.count(), "data": CouponRedemptionSerializer(items, many=True).data},
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Subscriptions - Web Checkout & Coupons"])
class WebPlansListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by("plan_type", "team_limit", "billing_type")
        return Response(
            {"success": True, "data": SubscriptionPlanSerializer(plans, many=True).data},
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Subscriptions - Web Checkout & Coupons"], request=CouponValidateSerializer)
class WebCouponValidateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CouponValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"].strip().upper()
        plan_id = serializer.validated_data["plan_id"]

        plan = SubscriptionPlan.objects.filter(id=plan_id, is_active=True).first()
        if not plan:
            raise ValidationError({"plan_id": "Selected subscription plan was not found."})

        coupon = DiscountCoupon.objects.filter(code=code).first()
        if not coupon:
            raise ValidationError({"code": "Invalid coupon code."})

        is_valid, reason = coupon.validate_for_plan_type(plan.plan_type)
        if not is_valid:
            raise ValidationError({"code": reason})

        discount_amount, final_price = coupon.compute_discount(plan.price)
        return Response(
            {
                "success": True,
                "valid": True,
                "data": {
                    "code": coupon.code,
                    "description": coupon.description,
                    "discount_type": coupon.discount_type,
                    "discount_value": str(coupon.discount_value),
                    "discount_period": coupon.get_discount_period_label(),
                    "discount_amount_label": coupon.get_discount_amount_label(),
                    "original_price": f"{Decimal(str(plan.price)):.2f}",
                    "discount_amount": f"{discount_amount:.2f}",
                    "final_price": f"{final_price:.2f}",
                    "currency": plan.currency or "USD",
                },
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Subscriptions - Web Checkout & Coupons"], request=WebCheckoutCreateSerializer)
class WebCheckoutCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = WebCheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = SubscriptionPlan.objects.filter(id=data["plan_id"], is_active=True).first()
        if not plan:
            raise ValidationError({"plan_id": "Subscription plan not found."})

        if request.user and request.user.is_authenticated:
            user = request.user
        else:
            email = (data.get("email") or "").strip().lower()
            password = data.get("password") or ""
            if not email or not password:
                raise ValidationError({"detail": "Email and password are required to subscribe on the web."})
            existing = User.objects.filter(email=email).first()
            if existing:
                auth_user = authenticate(username=email, password=password)
                if not auth_user:
                    raise ValidationError({"password": "Account already exists. Please enter the correct password."})
                user = auth_user
            else:
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    user_type=UserType.MAIN_USER,
                    is_active=True,
                    is_email_verified=True,
                    status=UserStatus.ACTIVE,
                )

        coupon = None
        coupon_code = (data.get("coupon_code") or "").strip().upper()
        if coupon_code:
            coupon = DiscountCoupon.objects.filter(code=coupon_code).first()
            if not coupon:
                raise ValidationError({"coupon_code": "Invalid coupon code."})
            is_valid, reason = coupon.validate_for_plan_type(plan.plan_type)
            if not is_valid:
                raise ValidationError({"coupon_code": reason})

        session_info = create_web_checkout_session(
            user=user,
            plan=plan,
            coupon=coupon,
            success_url=data.get("success_url", ""),
            cancel_url=data.get("cancel_url", ""),
        )

        # Track pending dummy checkout intent so dummy test confirmation works even without coupon
        if session_info["mode"] == "dummy":
            now = timezone.now()
            UserSubscription.objects.create(
                user=user,
                team=getattr(user, "owned_team", None) if plan.plan_type == PlanType.TEAM else None,
                plan=plan,
                status=UserSubscriptionStatus.PENDING,
                starts_at=now,
                last_renew_at=now,
                expires_at=now + timedelta(days=365 if plan.billing_type == BillingType.YEARLY else 30),
                payment_status=PaymentStatus.PENDING,
                latest_transaction_id=session_info["session_id"],
                discount_period=coupon.get_discount_period_label() if coupon else "0",
                discount_amount=coupon.get_discount_amount_label() if coupon else "0",
            )

        return Response(
            {
                "success": True,
                "stripe_configured": is_stripe_configured(),
                "data": {
                    "mode": session_info["mode"],
                    "session_id": session_info["session_id"],
                    "checkout_url": session_info["checkout_url"],
                    "plan_name": plan.name,
                    "original_price": f"{session_info['original_price']:.2f}",
                    "discount_amount": f"{session_info['discount_amount']:.2f}",
                    "final_price": f"{session_info['final_price']:.2f}",
                },
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Subscriptions - Web Checkout & Coupons"], request=WebCheckoutConfirmTestSerializer)
class WebCheckoutConfirmTestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if is_stripe_configured():
            raise ValidationError({"detail": "Test confirmation is disabled when live Stripe keys are configured."})

        serializer = WebCheckoutConfirmTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data["session_id"]

        redemption = CouponRedemption.objects.select_related("user", "plan", "coupon").filter(
            stripe_checkout_session_id=session_id
        ).first()
        pending_sub = UserSubscription.objects.select_related("user", "plan").filter(
            latest_transaction_id=session_id,
            status=UserSubscriptionStatus.PENDING,
        ).first()

        if not pending_sub and not redemption:
            raise ValidationError({"session_id": "Pending checkout session not found."})

        user = pending_sub.user if pending_sub else redemption.user
        plan = pending_sub.plan if pending_sub else redemption.plan
        coupon = redemption.coupon if redemption else None
        amount_paid = redemption.final_price if redemption else plan.price

        # Clear pending dummy row's unique latest_transaction_id before creating active sub
        if pending_sub:
            pending_sub.delete()

        subscription = activate_web_subscription_from_checkout(
            user=user,
            plan=plan,
            coupon=coupon,
            redemption=redemption,
            stripe_session_id=session_id,
            stripe_subscription_id=f"sub_dummy_{session_id[-12:]}",
            amount_paid=amount_paid,
        )
        return Response(
            {
                "success": True,
                "message": "Test web subscription activated successfully.",
                "data": UserSubscriptionSerializer(subscription).data,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(tags=["Subscriptions - Stripe Webhook"], summary="Receive Stripe webhook events")
    def post(self, request):
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event_type = process_stripe_webhook_event(request.body, sig_header)
            return Response({"status": "processed", "event": event_type}, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.warning("Stripe webhook error: %s", exc)
            return Response({"status": "error", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


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


