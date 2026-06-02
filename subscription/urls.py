from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .views import SubscriptionPlanViewSet

router = DefaultRouter()
router.register(r"subscription-plans", SubscriptionPlanViewSet, basename="subscription-plan", )

urlpatterns = [
    # path("subscription/", include(router.urls))
]

urlpatterns = router.urls
