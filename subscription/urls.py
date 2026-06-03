from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .views import SubscriptionPlanViewSet, UserSubscriptionViewSet

router = DefaultRouter()
router.register(r"subscription-plans", SubscriptionPlanViewSet, basename="subscription-plan")

router.register(r"subscription", UserSubscriptionViewSet, basename="subscription")

urlpatterns = [
    # path("subscription/", include(router.urls))
]

urlpatterns = router.urls
