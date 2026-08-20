from rest_framework.permissions import BasePermission
from core.constants import UserType

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

ADMIN_DASHBOARD_PERMISSIONS = [
    "admin_users",
    "admin_users.list",
    "admin_users.add",
    # "subscription_plans",
    # "subscription_plans.manage",
    # "discount_codes",
    # "discount_codes.manage",
    "user_accounts",
    "user_accounts.single",
    "user_accounts.teams",
    "user_accounts.fleet",
    "income_expenses",
    "income_expenses.subscription_payments",
    "income_expenses.fleet_payments",
    "income_expenses.history",
    "income_expenses.expenses",
    "reporting_analytics",
    "reporting_analytics.revenue_metrics",
    "support_tools",
    "support_tools.user_resources",
    "support_tools.staff_resources",
    "support_tools.email_system_login",
    "support_tools.support_tickets",
    "security_logging_compliance",
    "security_logging_compliance.audit_logs",
    "security_logging_compliance.data_protection",
]


def is_admin_dashboard_user(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.user_type == UserType.ADMIN
    )


def get_admin_dashboard_permissions(user):
    if not is_admin_dashboard_user(user):
        return []
    if user.is_superuser:
        return ADMIN_DASHBOARD_PERMISSIONS

    profile = getattr(user, "admin_profile", None)
    return profile.permissions_json if profile else []

class IsAdminUserPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.method in SAFE_METHODS or
            request.user and
            request.user.is_authenticated and
            request.user.user_type == UserType.ADMIN
        )


class IsSuperAdminUser(BasePermission):
    message = "Super admin access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(is_admin_dashboard_user(user) and user.is_superuser)


class HasAdminDashboardPermission(BasePermission):
    message = "Admin dashboard permission required."

    def has_permission(self, request, view):
        required_permission = getattr(view, "required_admin_permission", None)
        if required_permission is None:
            return is_admin_dashboard_user(request.user)
        return required_permission in get_admin_dashboard_permissions(request.user)

