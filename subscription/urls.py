from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .views import *


router = DefaultRouter()

router.register(r"subscription-plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register(r"subscription", UserSubscriptionViewSet, basename="subscription")
router.register(r"admin/subscribers/single", AdminSingleSubscriberViewSet, basename="admin-single-subscriber")
router.register(r"admin/subscribers/teams", AdminTeamSubscriberViewSet, basename="admin-team-subscriber")
router.register(r"admin/subscribers/fleets", AdminFleetAccountViewSet, basename="admin-fleet-account")
router.register(r"admin/coupons", AdminDiscountCouponViewSet, basename="admin-discount-coupon")

urlpatterns = [
    path("subscription/web-plans/", WebPlansListView.as_view(), name="subscription-web-plans"),
    path("subscription/coupons/validate/", WebCouponValidateView.as_view(), name="subscription-coupon-validate"),
    path("subscription/web-checkout/", WebCheckoutCreateView.as_view(), name="subscription-web-checkout"),
    path("subscription/web-checkout/confirm-test/", WebCheckoutConfirmTestView.as_view(), name="subscription-web-checkout-confirm-test"),
    path("subscription/stripe/webhook/", StripeWebhookView.as_view(), name="subscription-stripe-webhook"),
]

urlpatterns += router.urls
