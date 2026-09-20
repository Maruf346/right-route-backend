from django.urls import path
from analytics.views import (
    RevenueDashboardView,
    RevenueMetricsView,
    RevenueMixView,
    RevenueByPlanView,
    PlanPerformanceView,
    RevenueTimePeriodsView,
)

urlpatterns = [
    path("revenue/dashboard/", RevenueDashboardView.as_view(), name="revenue-dashboard"),
    path("revenue/metrics/", RevenueMetricsView.as_view(), name="revenue-metrics"),
    path("revenue/mix/", RevenueMixView.as_view(), name="revenue-mix"),
    path("revenue/by-plan/", RevenueByPlanView.as_view(), name="revenue-by-plan"),
    path("revenue/plan-performance/", PlanPerformanceView.as_view(), name="revenue-plan-performance"),
    path("revenue/time-periods/", RevenueTimePeriodsView.as_view(), name="revenue-time-periods"),
]
