from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .views import *


router = DefaultRouter()

router.register(r"subscription-plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register(r"subscription", UserSubscriptionViewSet, basename="subscription")
router.register(r"admin/subscribers/single", AdminSingleSubscriberViewSet, basename="admin-single-subscriber")
router.register(r"admin/subscribers/teams", AdminTeamSubscriberViewSet, basename="admin-team-subscriber")

urlpatterns = [
    # path("subscription/", include(router.urls))
]

urlpatterns = router.urls
