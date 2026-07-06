from django.urls import path, re_path, include
from .views import GetStartingWaypointViews

urlpatterns = [
    path("get-starting-waypoint/", GetStartingWaypointViews.as_view(), name="get-starting-waypoint")
]