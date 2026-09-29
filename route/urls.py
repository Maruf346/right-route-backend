from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminRouteHistoryDetailView,
    AdminRouteHistoryListView,
    AdminRouteHistoryWaypointsView,
    RouteViewSets,
)

router = DefaultRouter()
router.register(r"route", RouteViewSets, basename="route")

urlpatterns = [
    path("admin/route-history/", AdminRouteHistoryListView.as_view(), name="admin-route-history-list"),
    path("admin/route-history/<int:route_id>/", AdminRouteHistoryDetailView.as_view(), name="admin-route-history-detail"),
    path("admin/route-history/<int:route_id>/waypoints/", AdminRouteHistoryWaypointsView.as_view(), name="admin-route-history-waypoints"),
    path("", include(router.urls)),
]
