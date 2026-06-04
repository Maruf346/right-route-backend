from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .views import RouteViewSets

router = DefaultRouter()
router.register(r"route", RouteViewSets, basename="route")

urlpatterns = [
    path("", include(router.urls))
]

