from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from core.permissions import HasAdminDashboardPermission
from analytics.utils import (
    get_time_period_options,
    resolve_time_range,
    compute_pct_change,
    calculate_active_paying_accounts,
    calculate_mrr,
    calculate_arr,
    calculate_arpa,
    calculate_new_mrr,
    calculate_churned_mrr,
    calculate_total_revenue,
    calculate_revenue_mix,
    calculate_revenue_by_plan,
    calculate_plan_performance,
)
from analytics.serializers import (
    RevenueDashboardSerializer,
    RevenueMetricsCollectionSerializer,
    RevenueMixSerializer,
    RevenueByPlanItemSerializer,
    PlanPerformanceTableSerializer,
    TimePeriodOptionsSerializer,
)


def _build_metrics_payload(time_info):
    """Helper that computes all 7 metric cards using resolved time boundaries."""
    snap_curr = time_info["snapshot_current_date"]
    snap_prev = time_info["snapshot_compare_date"]
    snap_label = time_info["snapshot_compare_label"]

    per_curr_s = time_info["current_start"]
    per_curr_e = time_info["current_end"]
    per_prev_s = time_info["compare_start"]
    per_prev_e = time_info["compare_end"]
    per_label = time_info["period_compare_label"]

    # 1. Active Paying Accounts
    acc_curr = calculate_active_paying_accounts(snap_curr)
    acc_prev = calculate_active_paying_accounts(snap_prev)
    pct_acc, fmt_acc, pos_acc = compute_pct_change(acc_curr, acc_prev)

    # 2. MRR
    mrr_curr = calculate_mrr(snap_curr)
    mrr_prev = calculate_mrr(snap_prev)
    pct_mrr, fmt_mrr, pos_mrr = compute_pct_change(mrr_curr, mrr_prev)

    # 3. ARR
    arr_curr = calculate_arr(snap_curr)
    arr_prev = calculate_arr(snap_prev)
    pct_arr, fmt_arr, pos_arr = compute_pct_change(arr_curr, arr_prev)

    # 4. ARPA
    arpa_curr = calculate_arpa(snap_curr)
    arpa_prev = calculate_arpa(snap_prev)
    pct_arpa, fmt_arpa, pos_arpa = compute_pct_change(arpa_curr, arpa_prev)

    # 5. New MRR
    new_curr = calculate_new_mrr(per_curr_s, per_curr_e)
    new_prev = calculate_new_mrr(per_prev_s, per_prev_e)
    pct_new, fmt_new, pos_new = compute_pct_change(new_curr, new_prev)

    # 6. Churned MRR (lower is better -> reverse_good=True)
    churn_curr = calculate_churned_mrr(per_curr_s, per_curr_e)
    churn_prev = calculate_churned_mrr(per_prev_s, per_prev_e)
    pct_churn, fmt_churn, pos_churn = compute_pct_change(churn_curr, churn_prev, reverse_good=True)

    # 7. Total Revenue
    tot_curr = calculate_total_revenue(per_curr_s, per_curr_e)
    tot_prev = calculate_total_revenue(per_prev_s, per_prev_e)
    pct_tot, fmt_tot, pos_tot = compute_pct_change(tot_curr, tot_prev)

    return {
        "active_paying_accounts": {
            "value": Decimal(str(acc_curr)),
            "formatted_value": f"{acc_curr:,}",
            "percentage_change": pct_acc,
            "formatted_change": fmt_acc,
            "comparison_text": snap_label,
            "is_positive": pos_acc,
        },
        "mrr": {
            "value": mrr_curr,
            "formatted_value": f"${mrr_curr:,.2f}",
            "percentage_change": pct_mrr,
            "formatted_change": fmt_mrr,
            "comparison_text": snap_label,
            "is_positive": pos_mrr,
        },
        "arr": {
            "value": arr_curr,
            "formatted_value": f"${arr_curr:,.2f}",
            "percentage_change": pct_arr,
            "formatted_change": fmt_arr,
            "comparison_text": snap_label,
            "is_positive": pos_arr,
        },
        "arpa": {
            "value": arpa_curr,
            "formatted_value": f"${arpa_curr:,.2f}",
            "percentage_change": pct_arpa,
            "formatted_change": fmt_arpa,
            "comparison_text": snap_label,
            "is_positive": pos_arpa,
        },
        "new_mrr": {
            "value": new_curr,
            "formatted_value": f"${new_curr:,.2f}",
            "percentage_change": pct_new,
            "formatted_change": fmt_new,
            "comparison_text": per_label,
            "is_positive": pos_new,
        },
        "churned_mrr": {
            "value": churn_curr,
            "formatted_value": f"${churn_curr:,.2f}",
            "percentage_change": pct_churn,
            "formatted_change": fmt_churn,
            "comparison_text": per_label,
            "is_positive": pos_churn,
        },
        "total_revenue": {
            "value": tot_curr,
            "formatted_value": f"${tot_curr:,.2f}",
            "percentage_change": pct_tot,
            "formatted_change": fmt_tot,
            "comparison_text": per_label,
            "is_positive": pos_tot,
        },
    }


REVENUE_PARAMS = [
    OpenApiParameter("tab", OpenApiTypes.STR, description="Selected tab: 'last_30_days', 'qtd', 'ytd', or 'custom'"),
    OpenApiParameter("quarter", OpenApiTypes.STR, description="Quarter key for QTD (e.g. 'Q3_2026')"),
    OpenApiParameter("year", OpenApiTypes.INT, description="Year for YTD (e.g. 2026)"),
    OpenApiParameter("start_date", OpenApiTypes.STR, description="Start date for custom range (YYYY-MM-DD)"),
    OpenApiParameter("end_date", OpenApiTypes.STR, description="End date for custom range (YYYY-MM-DD)"),
]


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get Consolidated Revenue Dashboard (Metrics, Charts, and Table)",
    parameters=REVENUE_PARAMS,
    responses={200: RevenueDashboardSerializer},
)
class RevenueDashboardView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        time_info = resolve_time_range(request.query_params)
        options = get_time_period_options()
        metrics = _build_metrics_payload(time_info)
        mix = calculate_revenue_mix(time_info["snapshot_current_date"])
        by_plan = calculate_revenue_by_plan(time_info["snapshot_current_date"])
        plan_perf = calculate_plan_performance(time_info["current_start"], time_info["current_end"])

        data = {
            "tab": time_info["tab"],
            "time_period_options": options,
            "metrics": metrics,
            "revenue_mix": mix,
            "revenue_by_plan": by_plan,
            "plan_performance": plan_perf,
        }
        return Response(RevenueDashboardSerializer(data).data)


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get 7 Core Revenue Metrics Cards",
    parameters=REVENUE_PARAMS,
    responses={200: RevenueMetricsCollectionSerializer},
)
class RevenueMetricsView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        time_info = resolve_time_range(request.query_params)
        metrics = _build_metrics_payload(time_info)
        return Response(RevenueMetricsCollectionSerializer(metrics).data)


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get Revenue Mix by Customer Type (Donut Chart)",
    parameters=REVENUE_PARAMS,
    responses={200: RevenueMixSerializer},
)
class RevenueMixView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        time_info = resolve_time_range(request.query_params)
        mix = calculate_revenue_mix(time_info["snapshot_current_date"])
        return Response(RevenueMixSerializer(mix).data)


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get Revenue by Plan (Horizontal Bar Chart)",
    parameters=REVENUE_PARAMS,
    responses={200: RevenueByPlanItemSerializer(many=True)},
)
class RevenueByPlanView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        time_info = resolve_time_range(request.query_params)
        by_plan = calculate_revenue_by_plan(time_info["snapshot_current_date"])
        return Response(RevenueByPlanItemSerializer(by_plan, many=True).data)


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get Plan Performance Statistics Table",
    parameters=REVENUE_PARAMS,
    responses={200: PlanPerformanceTableSerializer},
)
class PlanPerformanceView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        time_info = resolve_time_range(request.query_params)
        plan_perf = calculate_plan_performance(time_info["current_start"], time_info["current_end"])
        return Response(PlanPerformanceTableSerializer(plan_perf).data)


@extend_schema(
    tags=["Reporting & Analytics - Revenue"],
    summary="Get Time Period Dropdown Options (Quarters and Years)",
    responses={200: TimePeriodOptionsSerializer},
)
class RevenueTimePeriodsView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "reporting_analytics.revenue_metrics"

    def get(self, request):
        options = get_time_period_options()
        return Response(TimePeriodOptionsSerializer(options).data)
