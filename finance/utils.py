import calendar
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from django.db.models import Sum, Q
from django.utils import timezone
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from subscription.models import UserSubscription, PurchaseInfo
from core.constants import UserSubscriptionStatus, PlanType


def parse_calendar_period(params):
    """
    Parses request query parameters to determine calendar date range and formatted display label.
    Modes:
      - 'day': target single date (e.g. July 5, 2026)
      - 'month': target full calendar month (e.g. July, 2026)
      - 'year': target calendar year up to today or year end (e.g. 2026)
    Default is today's date in 'day' mode.
    """
    today = timezone.now().date()
    period = params.get("period", "day").lower()

    # Parse date parameter if provided
    raw_date = params.get("date")
    target_date = today

    if raw_date:
        try:
            target_date = datetime.strptime(raw_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            target_date = today
    else:
        raw_year = params.get("year")
        raw_month = params.get("month")
        raw_day = params.get("day")

        year = int(raw_year) if raw_year and raw_year.isdigit() else today.year
        month = int(raw_month) if raw_month and raw_month.isdigit() else today.month
        day = int(raw_day) if raw_day and raw_day.isdigit() else today.day

        try:
            target_date = date(year, month, day)
        except ValueError:
            target_date = today

    if period == "month":
        year = target_date.year
        month = target_date.month
        num_days = calendar.monthrange(year, month)[1]
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        # Formatted label: e.g. "July, 2026"
        month_name = calendar.month_name[month]
        formatted_label = f"{month_name}, {year}"

    elif period == "year":
        year = target_date.year
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        # Formatted label: e.g. "2026"
        formatted_label = f"{year}"

    else:  # day
        period = "day"
        start_date = target_date
        end_date = target_date
        # Formatted label: e.g. "July 5, 2026"
        month_name = calendar.month_name[target_date.month]
        formatted_label = f"{month_name} {target_date.day}, {target_date.year}"

    return {
        "period": period,
        "target_date": target_date,
        "start_date": start_date,
        "end_date": end_date,
        "formatted_label": formatted_label,
    }


def calculate_subscription_revenue(start_date, end_date, period="day"):
    """
    Calculates expected/actual subscription revenue for the given date range.
    Uses active UserSubscription records joined with SubscriptionPlan price,
    and purchase transactions where available.
    """
    # Sum from verified purchase transactions within the date window
    purchase_total = PurchaseInfo.objects.filter(
        purchase_time__date__gte=start_date,
        purchase_time__date__lte=end_date,
        verification_status="VERIFIED",
    ).aggregate(total=Sum("subscription__plan__price"))["total"]

    if purchase_total is not None and purchase_total > 0:
        return Decimal(str(purchase_total))

    # Or calculate expected recurring revenue from active subscriptions active during this period
    active_subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=end_date,
        expires_at__date__gte=start_date,
    ).select_related("plan")

    total = Decimal("0.00")
    for sub in active_subs:
        if sub.plan and sub.plan.price:
            if period == "day":
                # Daily portion
                daily_rate = sub.plan.price / Decimal("30.0")
                total += daily_rate
            elif period == "month":
                total += sub.plan.price
            elif period == "year":
                if sub.plan.billing_type == "YEARLY":
                    total += sub.plan.price
                else:
                    total += sub.plan.price * Decimal("12.0")

    return total.quantize(Decimal("0.01"))


def calculate_fleet_revenue(start_date, end_date, period="day"):
    """
    Calculates expected fleet plan revenue for the given date range.
    TODO: Integrate dedicated fleet contract billing models once implemented.
    Currently aggregates subscriptions tied to Teams / Fleet plans.
    """
    fleet_subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        team__isnull=False,
        starts_at__date__lte=end_date,
        expires_at__date__gte=start_date,
    ).select_related("plan")

    total = Decimal("0.00")
    for sub in fleet_subs:
        if sub.plan and sub.plan.price:
            total += sub.plan.price

    return total.quantize(Decimal("0.01"))


def generate_expenses_excel_file(queryset):
    """
    Generates a professionally styled Excel (.xlsx) workbook for the given Expense queryset.
    Column headers per PDF spec:
    Vendor/Company | Date paid | Amount | Who paid | Payment method | Recurring | Description
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"

    # Header styling
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3"),
    )

    headers = [
        "Vendor/Company",
        "Date paid",
        "Amount",
        "Who paid",
        "Payment method",
        "Recurring",
        "Description",
    ]
    ws.append(headers)

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align

    # Add data rows
    row_num = 2
    for exp in queryset:
        date_str = exp.date_paid.strftime("%m/%d/%Y") if exp.date_paid else "-"
        ws.append([
            exp.vendor_company,
            date_str,
            float(exp.amount),
            exp.who_paid,
            exp.payment_method,
            exp.recurring,
            exp.description,
        ])

        # Style data cells
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=row_num, column=col_num)
            cell.border = thin_border
            if col_num == 3:  # Amount
                cell.number_format = "$#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col_num in (2, 5, 6):
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="left")

        row_num += 1

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
