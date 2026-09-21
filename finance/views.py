from decimal import Decimal
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes

from core.permissions import HasAdminDashboardPermission
from account.models import Team, User
from subscription.models import UserSubscription
from finance.models import Expense
from finance.serializers import (
    ExpenseSerializer,
    FinanceSummarySerializer,
    FleetPaymentItemSerializer,
)
from finance.utils import (
    parse_calendar_period,
    calculate_subscription_revenue,
    calculate_fleet_revenue,
    generate_expenses_excel_file,
)


class FleetPagination(PageNumberPagination):
    page_size = 6
    page_size_query_param = "page_size"
    max_page_size = 100


class ExpensePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(
    tags=["Finance - Income & Expenses"],
    summary="Get Subscription Payments revenue summary for Orange Bar",
    parameters=[
        OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day' (default), 'month', or 'year'"),
        OpenApiParameter("date", OpenApiTypes.STR, description="Target date in YYYY-MM-DD format"),
        OpenApiParameter("year", OpenApiTypes.INT, description="Year integer (e.g. 2026)"),
        OpenApiParameter("month", OpenApiTypes.INT, description="Month integer (1-12)"),
        OpenApiParameter("day", OpenApiTypes.INT, description="Day integer (1-31)"),
    ],
    responses={200: FinanceSummarySerializer},
)
class SubscriptionPaymentsSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.subscription_payments"

    def get(self, request):
        parsed = parse_calendar_period(request.query_params)
        total = calculate_subscription_revenue(
            parsed["start_date"], parsed["end_date"], parsed["period"]
        )

        formatted_total = f"${total:,.2f}".rstrip("0").rstrip(".") if total == int(total) else f"${total:,.2f}"
        display_bar_text = f"{parsed['formatted_label']}: {formatted_total}"

        data = {
            "period": parsed["period"],
            "target_date": parsed["target_date"],
            "start_date": parsed["start_date"],
            "end_date": parsed["end_date"],
            "formatted_label": parsed["formatted_label"],
            "total_amount": total,
            "formatted_total": formatted_total,
            "display_bar_text": display_bar_text,
        }
        return Response(FinanceSummarySerializer(data).data)


@extend_schema(
    tags=["Finance - Income & Expenses"],
    summary="Get Fleet Payments expected revenue summary for Orange Bar",
    parameters=[
        OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day' (default), 'month', or 'year'"),
        OpenApiParameter("date", OpenApiTypes.STR, description="Target date in YYYY-MM-DD format"),
        OpenApiParameter("year", OpenApiTypes.INT, description="Year integer (e.g. 2026)"),
        OpenApiParameter("month", OpenApiTypes.INT, description="Month integer (1-12)"),
        OpenApiParameter("day", OpenApiTypes.INT, description="Day integer (1-31)"),
    ],
    responses={200: FinanceSummarySerializer},
)
class FleetPaymentsSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.fleet_payments"

    def get(self, request):
        parsed = parse_calendar_period(request.query_params)
        total = calculate_fleet_revenue(
            parsed["start_date"], parsed["end_date"], parsed["period"]
        )

        formatted_total = f"${total:,.2f}".rstrip("0").rstrip(".") if total == int(total) else f"${total:,.2f}"
        display_bar_text = f"{parsed['formatted_label']}: {formatted_total}"

        data = {
            "period": parsed["period"],
            "target_date": parsed["target_date"],
            "start_date": parsed["start_date"],
            "end_date": parsed["end_date"],
            "formatted_label": parsed["formatted_label"],
            "total_amount": total,
            "formatted_total": formatted_total,
            "display_bar_text": display_bar_text,
        }
        return Response(FinanceSummarySerializer(data).data)


@extend_schema(
    tags=["Finance - Income & Expenses"],
    summary="List Fleet Plans with payments due in the selected period",
    parameters=[
        OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day' (default), 'month', or 'year'"),
        OpenApiParameter("date", OpenApiTypes.STR, description="Target date in YYYY-MM-DD format"),
        OpenApiParameter("year", OpenApiTypes.INT, description="Year integer (e.g. 2026)"),
        OpenApiParameter("month", OpenApiTypes.INT, description="Month integer (1-12)"),
        OpenApiParameter("day", OpenApiTypes.INT, description="Day integer (1-31)"),
    ],
    responses={200: FleetPaymentItemSerializer(many=True)},
)
class FleetPaymentsListView(APIView):
    """
    List of active fleet plans for a selected day, month or year.
    TODO: Once fleet contract billing is implemented, link to dedicated invoice schedule models.
    """
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.fleet_payments"
    pagination_class = FleetPagination

    def get(self, request):
        parsed = parse_calendar_period(request.query_params)
        
        # Query active teams / fleet plans
        teams = Team.objects.filter(is_active=True).select_related("owner").order_by("name")

        items = []
        for team in teams:
            # Look up subscription
            sub = team.subscriptions.order_by("-created_at").first()
            plan_name = sub.plan.name if sub and sub.plan else "Fleet Custom"
            amount = sub.plan.price if sub and sub.plan else Decimal("0.00")
            due_date = sub.expires_at.date() if sub and sub.expires_at else None

            # Filter if date range applies
            if due_date and (due_date < parsed["start_date"] or due_date > parsed["end_date"]):
                continue

            items.append({
                "id": team.id,
                "company_name": team.name,
                "owner_email": team.owner.email if team.owner else "",
                "plan_name": plan_name,
                "driver_limit": team.max_members,
                "amount_due": amount,
                "formatted_amount": f"${amount:,.2f}",
                "due_date": due_date,
                "status": "Active" if team.is_active else "Inactive",
                "user_account_id": team.owner.id if team.owner else None,
            })

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(items, request)
        if page is not None:
            return paginator.get_paginated_response(page)

        return Response(FleetPaymentItemSerializer(items, many=True).data)


@extend_schema(
    tags=["Finance - Income & Expenses"],
    summary="Get Expenses total summary for Orange Bar",
    parameters=[
        OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day' (default), 'month', or 'year'"),
        OpenApiParameter("date", OpenApiTypes.STR, description="Target date in YYYY-MM-DD format"),
        OpenApiParameter("year", OpenApiTypes.INT, description="Year integer (e.g. 2026)"),
        OpenApiParameter("month", OpenApiTypes.INT, description="Month integer (1-12)"),
        OpenApiParameter("day", OpenApiTypes.INT, description="Day integer (1-31)"),
    ],
    responses={200: FinanceSummarySerializer},
)
class ExpenseSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.expenses"

    def get(self, request):
        parsed = parse_calendar_period(request.query_params)
        total = Expense.objects.filter(
            date_paid__gte=parsed["start_date"],
            date_paid__lte=parsed["end_date"],
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        formatted_total = f"${total:,.2f}".rstrip("0").rstrip(".") if total == int(total) else f"${total:,.2f}"
        display_bar_text = f"{parsed['formatted_label']}: {formatted_total}"

        data = {
            "period": parsed["period"],
            "target_date": parsed["target_date"],
            "start_date": parsed["start_date"],
            "end_date": parsed["end_date"],
            "formatted_label": parsed["formatted_label"],
            "total_amount": total,
            "formatted_total": formatted_total,
            "display_bar_text": display_bar_text,
        }
        return Response(FinanceSummarySerializer(data).data)


@extend_schema_view(
    list=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="List recorded expenses (filterable by date range or search)",
        parameters=[
            OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day', 'month', or 'year'"),
            OpenApiParameter("date", OpenApiTypes.STR, description="Date filter YYYY-MM-DD"),
            OpenApiParameter("start_date", OpenApiTypes.STR, description="Explicit start date YYYY-MM-DD"),
            OpenApiParameter("end_date", OpenApiTypes.STR, description="Explicit end date YYYY-MM-DD"),
            OpenApiParameter("vendor", OpenApiTypes.STR, description="Filter by vendor/company name"),
            OpenApiParameter("who_paid", OpenApiTypes.STR, description="Filter by payer name"),
            OpenApiParameter("payment_method", OpenApiTypes.STR, description="Filter by payment method"),
            OpenApiParameter("recurring", OpenApiTypes.STR, description="Filter by recurring (No, Monthly, Yearly)"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Search query across vendor, payer, and description"),
        ],
    ),
    retrieve=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="Get expense details (Expense Log view)",
    ),
    create=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="Record a new expense (Add New Expense form)",
    ),
    update=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="Update an existing expense (Edit Expense form)",
    ),
    partial_update=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="Update an existing expense (Edit Expense form)",
    ),
    destroy=extend_schema(
        tags=["Finance - Income & Expenses"],
        summary="Delete an expense",
    ),
)
class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().select_related("created_by")
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.expenses"
    pagination_class = ExpensePagination

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        # Date range filtering
        if "start_date" in params or "end_date" in params:
            start_date = params.get("start_date")
            end_date = params.get("end_date")
            if start_date:
                qs = qs.filter(date_paid__gte=start_date)
            if end_date:
                qs = qs.filter(date_paid__lte=end_date)
        elif "period" in params or "date" in params or "year" in params or "month" in params or "day" in params:
            parsed = parse_calendar_period(params)
            qs = qs.filter(date_paid__gte=parsed["start_date"], date_paid__lte=parsed["end_date"])

        # Filters
        vendor = params.get("vendor")
        if vendor:
            qs = qs.filter(vendor_company__icontains=vendor.strip())

        who_paid = params.get("who_paid")
        if who_paid:
            qs = qs.filter(who_paid__icontains=who_paid.strip())

        method = params.get("payment_method")
        if method:
            qs = qs.filter(payment_method__iexact=method.strip())

        recurring = params.get("recurring")
        if recurring:
            qs = qs.filter(recurring__iexact=recurring.strip())

        search = params.get("search")
        if search:
            s = search.strip()
            qs = qs.filter(
                Q(vendor_company__icontains=s)
                | Q(who_paid__icontains=s)
                | Q(description__icontains=s)
            )

        return qs.order_by("-date_paid", "-created_at")


@extend_schema(
    tags=["Finance - Income & Expenses"],
    summary="Download Excel (.xlsx) spreadsheet of recorded expenses",
    parameters=[
        OpenApiParameter("period", OpenApiTypes.STR, description="Granularity: 'day', 'month', or 'year'"),
        OpenApiParameter("date", OpenApiTypes.STR, description="Date filter YYYY-MM-DD"),
        OpenApiParameter("start_date", OpenApiTypes.STR, description="Explicit start date YYYY-MM-DD"),
        OpenApiParameter("end_date", OpenApiTypes.STR, description="Explicit end date YYYY-MM-DD"),
        OpenApiParameter("search", OpenApiTypes.STR, description="Search term filter"),
    ],
    responses={200: OpenApiTypes.BINARY},
)
class ExpenseExportView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "income_expenses.expenses"

    def get(self, request):
        params = request.query_params
        qs = Expense.objects.all()

        if "start_date" in params or "end_date" in params:
            start_date = params.get("start_date")
            end_date = params.get("end_date")
            if start_date:
                qs = qs.filter(date_paid__gte=start_date)
            if end_date:
                qs = qs.filter(date_paid__lte=end_date)
        elif "period" in params or "date" in params or "year" in params or "month" in params or "day" in params:
            parsed = parse_calendar_period(params)
            qs = qs.filter(date_paid__gte=parsed["start_date"], date_paid__lte=parsed["end_date"])

        search = params.get("search")
        if search:
            s = search.strip()
            qs = qs.filter(
                Q(vendor_company__icontains=s)
                | Q(who_paid__icontains=s)
                | Q(description__icontains=s)
            )

        qs = qs.order_by("-date_paid", "-created_at")

        excel_file = generate_expenses_excel_file(qs)
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        filename = f"RightRoute_Expenses_{timestamp}.xlsx"

        response = HttpResponse(
            excel_file.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
