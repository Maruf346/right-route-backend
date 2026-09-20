import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.db.models import Sum, Q, Count
from django.utils import timezone

from subscription.models import UserSubscription, SubscriptionPlan, PurchaseInfo
from account.models import Team, User
from core.constants import UserSubscriptionStatus, PlanType, BillingType
from analytics.constants import STANDARD_PLAN_NAMES


def get_quarter_dates(year, quarter_num):
    """Returns (start_date, end_date) for a given year and quarter (1-4)."""
    if quarter_num == 1:
        return date(year, 1, 1), date(year, 3, 31)
    elif quarter_num == 2:
        return date(year, 4, 1), date(year, 6, 30)
    elif quarter_num == 3:
        return date(year, 7, 1), date(year, 9, 30)
    elif quarter_num == 4:
        return date(year, 10, 1), date(year, 12, 31)
    raise ValueError(f"Invalid quarter number: {quarter_num}")


def get_current_quarter_num(target_date):
    """Returns 1, 2, 3, or 4 for given date."""
    return (target_date.month - 1) // 3 + 1


def get_time_period_options():
    """
    Generates dynamic dropdown options:
    - 2 years worth of quarters (with current quarter marked '... to Date')
    - 4 years worth of YTD options (with current year marked '... YTD')
    """
    today = timezone.now().date()
    curr_year = today.year
    curr_quarter = get_current_quarter_num(today)

    quarters = []
    # Generate 8 quarters going backwards
    y = curr_year
    q = curr_quarter
    for i in range(8):
        if i == 0:
            label = f"Q{q} {y} to Date"
            is_current = True
        else:
            label = f"Q{q} {y}"
            is_current = False
        quarters.append({
            "key": f"Q{q}_{y}",
            "year": y,
            "quarter": q,
            "label": label,
            "is_current": is_current,
        })
        q -= 1
        if q < 1:
            q = 4
            y -= 1

    years = []
    # Generate 4 years
    for i in range(4):
        year_val = curr_year - i
        label = f"{year_val} YTD" if i == 0 else str(year_val)
        years.append({
            "year": year_val,
            "label": label,
            "is_current": (i == 0),
        })

    return {
        "quarters": quarters,
        "years": years,
        "default_quarter": quarters[0]["key"],
        "default_year": years[0]["year"],
    }


def resolve_time_range(params):
    """
    Resolves request parameters into:
    - `tab`: 'last_30_days', 'qtd', 'ytd', 'custom'
    - `current_start`, `current_end`: current evaluation date window
    - `compare_start`, `compare_end`: comparison window for period metrics
    - `snapshot_current_date`: snapshot date for snapshot metrics (MRR, ARR, etc.)
    - `snapshot_compare_date`: comparison date for snapshot metrics
    - `snapshot_compare_label`: text like 'vs 30 days ago', 'since quarter start', 'since year start'
    - `period_compare_label`: text like 'vs previous 30 days', 'vs previous quarter period', 'vs previous year'
    """
    today = timezone.now().date()
    tab = params.get("tab", "last_30_days").lower()

    if tab == "qtd":
        raw_quarter = params.get("quarter")  # e.g. "Q3_2026" or "Q3 2026"
        curr_quarter_num = get_current_quarter_num(today)
        target_year = today.year
        target_q_num = curr_quarter_num

        if raw_quarter:
            clean_q = raw_quarter.replace(" ", "_").upper()
            parts = clean_q.split("_")
            if len(parts) >= 2:
                try:
                    target_q_num = int(parts[0].replace("Q", ""))
                    target_year = int(parts[1])
                except ValueError:
                    pass

        q_start, q_end = get_quarter_dates(target_year, target_q_num)
        is_current_q = (target_year == today.year and target_q_num == curr_quarter_num)

        if is_current_q:
            current_start = q_start
            current_end = today
            snapshot_current_date = today
            snapshot_compare_date = q_start
            # Number of days elapsed in current quarter
            days_elapsed = (today - q_start).days
            # Compare with previous quarter matching days
            prev_q_num = target_q_num - 1 if target_q_num > 1 else 4
            prev_q_year = target_year if target_q_num > 1 else target_year - 1
            prev_q_start, _ = get_quarter_dates(prev_q_year, prev_q_num)
            compare_start = prev_q_start
            compare_end = prev_q_start + timedelta(days=days_elapsed)
        else:
            current_start = q_start
            current_end = q_end
            snapshot_current_date = q_end
            snapshot_compare_date = q_start
            prev_q_num = target_q_num - 1 if target_q_num > 1 else 4
            prev_q_year = target_year if target_q_num > 1 else target_year - 1
            compare_start, compare_end = get_quarter_dates(prev_q_year, prev_q_num)

        snapshot_compare_label = "since quarter start"
        period_compare_label = "vs previous quarter period"

    elif tab == "ytd":
        raw_year = params.get("year")
        target_year = int(raw_year) if raw_year and str(raw_year).isdigit() else today.year
        is_current_y = (target_year == today.year)

        if is_current_y:
            current_start = date(target_year, 1, 1)
            current_end = today
            snapshot_current_date = today
            snapshot_compare_date = date(target_year, 1, 1)
            # Compare with same days in previous year
            days_elapsed = (today - current_start).days
            prev_year_start = date(target_year - 1, 1, 1)
            compare_start = prev_year_start
            compare_end = prev_year_start + timedelta(days=days_elapsed)
        else:
            current_start = date(target_year, 1, 1)
            current_end = date(target_year, 12, 31)
            snapshot_current_date = date(target_year, 12, 31)
            snapshot_compare_date = date(target_year, 1, 1)
            compare_start = date(target_year - 1, 1, 1)
            compare_end = date(target_year - 1, 12, 31)

        snapshot_compare_label = "since year start"
        period_compare_label = "vs previous matching period"

    elif tab == "custom":
        raw_start = params.get("start_date")
        raw_end = params.get("end_date")
        try:
            current_start = datetime.strptime(raw_start.strip(), "%Y-%m-%d").date() if raw_start else today - timedelta(days=30)
            current_end = datetime.strptime(raw_end.strip(), "%Y-%m-%d").date() if raw_end else today
        except ValueError:
            current_start = today - timedelta(days=30)
            current_end = today

        snapshot_current_date = current_end
        snapshot_compare_date = current_start
        # Compare with matching range of previous year
        duration = (current_end - current_start).days
        try:
            compare_start = date(current_start.year - 1, current_start.month, current_start.day)
            compare_end = compare_start + timedelta(days=duration)
        except ValueError:
            compare_start = current_start - timedelta(days=365)
            compare_end = compare_start + timedelta(days=duration)

        snapshot_compare_label = "since range start"
        period_compare_label = "vs previous year range"

    else:  # last_30_days default
        tab = "last_30_days"
        current_end = today
        current_start = today - timedelta(days=30)
        snapshot_current_date = today
        snapshot_compare_date = today - timedelta(days=30)
        compare_end = today - timedelta(days=31)
        compare_start = today - timedelta(days=60)
        snapshot_compare_label = "vs 30 days ago"
        period_compare_label = "vs previous 30 days"

    return {
        "tab": tab,
        "current_start": current_start,
        "current_end": current_end,
        "compare_start": compare_start,
        "compare_end": compare_end,
        "snapshot_current_date": snapshot_current_date,
        "snapshot_compare_date": snapshot_compare_date,
        "snapshot_compare_label": snapshot_compare_label,
        "period_compare_label": period_compare_label,
    }


def compute_pct_change(current, previous, reverse_good=False):
    """
    Computes percentage change: ((current - previous) / previous) * 100.
    Returns (percentage_float, formatted_string, is_positive_for_ui).
    """
    curr_dec = Decimal(str(current or 0))
    prev_dec = Decimal(str(previous or 0))

    if prev_dec == Decimal("0"):
        if curr_dec > Decimal("0"):
            return 100.0, "+100.0%", not reverse_good
        return 0.0, "0.0%", True

    pct = ((curr_dec - prev_dec) / prev_dec) * Decimal("100")
    pct_float = round(float(pct), 2)
    formatted = f"{'+' if pct_float > 0 else ''}{pct_float:.2f}%"

    is_positive = (pct_float >= 0) if not reverse_good else (pct_float <= 0)
    return pct_float, formatted, is_positive


# ── Metric Calculators ────────────────────────────────────────────────────────

def calculate_active_paying_accounts(target_date):
    """
    Counts unique active paying accounts (Single, Team, Fleet) as of target_date.
    """
    # Active user subscriptions
    user_count = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=target_date,
        expires_at__date__gte=target_date,
    ).values("user").distinct().count()

    # Active teams with active plan
    team_count = Team.objects.filter(
        is_active=True,
        subscriptions__status=UserSubscriptionStatus.ACTIVE,
        subscriptions__starts_at__date__lte=target_date,
        subscriptions__expires_at__date__gte=target_date,
    ).distinct().count()

    # TODO: Add dedicated fleet contract accounts once fleet models are implemented.
    fleet_count = 0

    return max(user_count, team_count + user_count - team_count)


def calculate_mrr(target_date):
    """
    Calculates snapshot Monthly Recurring Revenue as of target_date.
    Formula: Single monthly + Team monthly + (Single annual / 12) + (Team annual / 12) + Fleet monthly + (Fleet annual / 12)
    """
    subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=target_date,
        expires_at__date__gte=target_date,
    ).select_related("plan")

    mrr = Decimal("0.00")
    for sub in subs:
        if sub.plan and sub.plan.price:
            price = Decimal(str(sub.plan.price))
            if sub.plan.billing_type == BillingType.YEARLY:
                mrr += price / Decimal("12.0")
            else:
                mrr += price

    # TODO: Add fleet contracts MRR once fleet models are implemented
    fleet_mrr = calculate_fleet_mrr(target_date)
    mrr += fleet_mrr

    return mrr.quantize(Decimal("0.01"))


def calculate_fleet_mrr(target_date):
    """
    Helper for fleet recurring revenue.
    TODO: Connect dedicated fleet contract models when implemented.
    """
    return Decimal("0.00")


def calculate_arr(target_date):
    """ARR = MRR * 12"""
    return (calculate_mrr(target_date) * Decimal("12.0")).quantize(Decimal("0.01"))


def calculate_arpa(target_date):
    """ARPA = MRR / Active Paying Accounts"""
    mrr = calculate_mrr(target_date)
    accounts = calculate_active_paying_accounts(target_date)
    if accounts > 0:
        return (mrr / Decimal(str(accounts))).quantize(Decimal("0.01"))
    return Decimal("0.00")


def calculate_new_mrr(start_date, end_date):
    """
    Period Metric: Sum of new monthly recurring revenue added during start_date to end_date.
    """
    new_subs = UserSubscription.objects.filter(
        starts_at__date__gte=start_date,
        starts_at__date__lte=end_date,
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
    ).select_related("plan")

    total_new = Decimal("0.00")
    for sub in new_subs:
        if sub.plan and sub.plan.price:
            price = Decimal(str(sub.plan.price))
            if sub.plan.billing_type == BillingType.YEARLY:
                total_new += price / Decimal("12.0")
            else:
                total_new += price

    return total_new.quantize(Decimal("0.01"))


def calculate_churned_mrr(start_date, end_date):
    """
    Period Metric: Sum of recurring revenue lost during start_date to end_date.
    """
    churned_subs = UserSubscription.objects.filter(
        Q(cancelled_at__date__gte=start_date, cancelled_at__date__lte=end_date)
        | Q(expires_at__date__gte=start_date, expires_at__date__lte=end_date, status__in=[
            UserSubscriptionStatus.CANCELLED,
            UserSubscriptionStatus.EXPIRED,
            UserSubscriptionStatus.FAILED,
        ])
    ).select_related("plan")

    churned = Decimal("0.00")
    for sub in churned_subs:
        if sub.plan and sub.plan.price:
            price = Decimal(str(sub.plan.price))
            if sub.plan.billing_type == BillingType.YEARLY:
                churned += price / Decimal("12.0")
            else:
                churned += price

    return churned.quantize(Decimal("0.01"))


def calculate_total_revenue(start_date, end_date):
    """
    Period Metric: Actual collected cash from subscriptions / purchases during start_date to end_date.
    """
    purchase_sum = PurchaseInfo.objects.filter(
        purchase_time__date__gte=start_date,
        purchase_time__date__lte=end_date,
        verification_status="VERIFIED",
    ).aggregate(total=Sum("subscription__plan__price"))["total"]

    if purchase_sum is not None:
        return Decimal(str(purchase_sum)).quantize(Decimal("0.01"))

    # Fallback to active subscriptions that started in this period
    sub_sum = UserSubscription.objects.filter(
        starts_at__date__gte=start_date,
        starts_at__date__lte=end_date,
    ).aggregate(total=Sum("plan__price"))["total"]

    return Decimal(str(sub_sum or "0.00")).quantize(Decimal("0.01"))


# ── Chart & Breakdown Engines ─────────────────────────────────────────────────

def calculate_revenue_mix(target_date):
    """
    Section 4 — Revenue Mix by Customer Type Donut Chart.
    Breakdown: Single, Team, Fleet. Center value: Current ARR.
    """
    subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=target_date,
        expires_at__date__gte=target_date,
    ).select_related("plan")

    single_mrr = Decimal("0.00")
    team_mrr = Decimal("0.00")
    fleet_mrr = Decimal("0.00")

    for sub in subs:
        if sub.plan and sub.plan.price:
            price = Decimal(str(sub.plan.price))
            mrr_val = (price / Decimal("12.0")) if sub.plan.billing_type == BillingType.YEARLY else price
            if sub.team is not None or sub.plan.plan_type == PlanType.TEAM:
                team_mrr += mrr_val
            else:
                single_mrr += mrr_val

    # Fleet calculations
    fleet_mrr += calculate_fleet_mrr(target_date)

    total_mrr = single_mrr + team_mrr + fleet_mrr
    center_arr = total_mrr * Decimal("12.0")

    def calc_pct(val):
        if total_mrr > Decimal("0.00"):
            return round(float((val / total_mrr) * Decimal("100.0")), 2)
        return 0.0

    return {
        "center_arr": center_arr,
        "formatted_arr": f"${center_arr:,.2f}",
        "total_mrr": total_mrr,
        "items": [
            {
                "customer_type": "Single",
                "revenue": single_mrr,
                "formatted_revenue": f"${single_mrr:,.2f}",
                "percentage": calc_pct(single_mrr),
            },
            {
                "customer_type": "Team",
                "revenue": team_mrr,
                "formatted_revenue": f"${team_mrr:,.2f}",
                "percentage": calc_pct(team_mrr),
            },
            {
                "customer_type": "Fleet",
                "revenue": fleet_mrr,
                "formatted_revenue": f"${fleet_mrr:,.2f}",
                "percentage": calc_pct(fleet_mrr),
            },
        ],
    }


def calculate_revenue_by_plan(target_date):
    """
    Section 5 — Revenue by Plan Horizontal Bar Chart.
    Calculates monthly recurring revenue for each plan and sorts highest to lowest.
    """
    plans = SubscriptionPlan.objects.filter(is_active=True)
    plan_mrr_map = {name: Decimal("0.00") for name in STANDARD_PLAN_NAMES}

    subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=target_date,
        expires_at__date__gte=target_date,
    ).select_related("plan")

    for sub in subs:
        if sub.plan and sub.plan.price:
            price = Decimal(str(sub.plan.price))
            mrr_val = (price / Decimal("12.0")) if sub.plan.billing_type == BillingType.YEARLY else price
            
            # Map plan name to standard categories
            p_name = sub.plan.name
            if "annual" in p_name.lower() or "yearly" in p_name.lower():
                plan_key = "Single Annual"
            elif "single" in p_name.lower() or "individual" in p_name.lower():
                plan_key = "Single Monthly"
            elif "fleet" in p_name.lower():
                plan_key = "Fleet"
            elif sub.plan.team_limit in (5, 10, 25, 50, 100):
                plan_key = f"Team {sub.plan.team_limit}"
            else:
                plan_key = p_name if p_name in plan_mrr_map else "Single Monthly"

            plan_mrr_map[plan_key] = plan_mrr_map.get(plan_key, Decimal("0.00")) + mrr_val

    total_mrr = sum(plan_mrr_map.values(), Decimal("0.00"))

    items = []
    for plan_name, mrr_val in plan_mrr_map.items():
        pct = round(float((mrr_val / total_mrr) * Decimal("100.0")), 2) if total_mrr > 0 else 0.0
        items.append({
            "plan_name": plan_name,
            "mrr": mrr_val,
            "formatted_mrr": f"${mrr_val:,.2f}",
            "percentage": pct,
        })

    # Sort highest revenue to lowest revenue per specification
    items.sort(key=lambda x: x["mrr"], reverse=True)
    return items


def calculate_plan_performance(start_date, end_date):
    """
    Section 6 — Plan Performance Chart.
    Rows for each plan + Total row with drivers/seats and non-averaged churn rate.
    """
    plan_data = {
        name: {
            "plan": name,
            "active_accounts": 0,
            "drivers_or_seats": 0,
            "mrr": Decimal("0.00"),
            "accounts_lost": 0,
            "accounts_start": 0,
        }
        for name in STANDARD_PLAN_NAMES
    }

    # Active accounts at end date
    active_subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=end_date,
        expires_at__date__gte=end_date,
    ).select_related("plan", "team")

    for sub in active_subs:
        if sub.plan:
            p_name = sub.plan.name
            if "annual" in p_name.lower() or "yearly" in p_name.lower():
                key = "Single Annual"
                seats = 1
            elif "single" in p_name.lower() or "individual" in p_name.lower():
                key = "Single Monthly"
                seats = 1
            elif "fleet" in p_name.lower():
                key = "Fleet"
                seats = sub.team.max_members if sub.team else 100
            elif sub.plan.team_limit in (5, 10, 25, 50, 100):
                key = f"Team {sub.plan.team_limit}"
                seats = sub.plan.team_limit
            else:
                key = "Single Monthly"
                seats = 1

            price = Decimal(str(sub.plan.price))
            mrr_val = (price / Decimal("12.0")) if sub.plan.billing_type == BillingType.YEARLY else price

            plan_data[key]["active_accounts"] += 1
            plan_data[key]["drivers_or_seats"] += seats
            plan_data[key]["mrr"] += mrr_val

    # Count churned per plan
    churned_subs = UserSubscription.objects.filter(
        Q(cancelled_at__date__gte=start_date, cancelled_at__date__lte=end_date)
        | Q(expires_at__date__gte=start_date, expires_at__date__lte=end_date, status__in=[
            UserSubscriptionStatus.CANCELLED,
            UserSubscriptionStatus.EXPIRED,
            UserSubscriptionStatus.FAILED,
        ])
    ).select_related("plan")

    for sub in churned_subs:
        if sub.plan:
            p_name = sub.plan.name
            key = "Single Monthly"
            if "annual" in p_name.lower() or "yearly" in p_name.lower():
                key = "Single Annual"
            elif "fleet" in p_name.lower():
                key = "Fleet"
            elif sub.plan.team_limit in (5, 10, 25, 50, 100):
                key = f"Team {sub.plan.team_limit}"
            plan_data[key]["accounts_lost"] += 1

    # Accounts active at beginning
    start_subs = UserSubscription.objects.filter(
        status__in=[UserSubscriptionStatus.ACTIVE, UserSubscriptionStatus.TRIAL],
        starts_at__date__lte=start_date,
        expires_at__date__gte=start_date,
    ).select_related("plan")

    for sub in start_subs:
        if sub.plan:
            p_name = sub.plan.name
            key = "Single Monthly"
            if "annual" in p_name.lower() or "yearly" in p_name.lower():
                key = "Single Annual"
            elif "fleet" in p_name.lower():
                key = "Fleet"
            elif sub.plan.team_limit in (5, 10, 25, 50, 100):
                key = f"Team {sub.plan.team_limit}"
            plan_data[key]["accounts_start"] += 1

    rows = []
    tot_accounts = 0
    tot_seats = 0
    tot_mrr = Decimal("0.00")
    tot_lost = 0
    tot_start = 0

    for name in STANDARD_PLAN_NAMES:
        d = plan_data[name]
        start_count = d["accounts_start"] or d["active_accounts"]
        churn_pct = round((d["accounts_lost"] / start_count) * 100.0, 2) if start_count > 0 else 0.0

        rows.append({
            "plan": name,
            "active_accounts": d["active_accounts"],
            "drivers_or_seats": d["drivers_or_seats"],
            "mrr": d["mrr"],
            "formatted_mrr": f"${d['mrr']:,.2f}",
            "churn_rate": churn_pct,
            "formatted_churn_rate": f"{churn_pct:.2f}%",
        })

        tot_accounts += d["active_accounts"]
        tot_seats += d["drivers_or_seats"]
        tot_mrr += d["mrr"]
        tot_lost += d["accounts_lost"]
        tot_start += start_count

    tot_churn_pct = round((tot_lost / tot_start) * 100.0, 2) if tot_start > 0 else 0.0

    total_row = {
        "plan": "Total",
        "active_accounts": tot_accounts,
        "drivers_or_seats": tot_seats,
        "mrr": tot_mrr,
        "formatted_mrr": f"${tot_mrr:,.2f}",
        "churn_rate": tot_churn_pct,
        "formatted_churn_rate": f"{tot_churn_pct:.2f}%",
    }

    return {"rows": rows, "total": total_row}
