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


def has_admin_dashboard_permission(user, required_permissions):
    if isinstance(required_permissions, str):
        required_permissions = [required_permissions]

    user_permissions = set(get_admin_dashboard_permissions(user))
    for permission in required_permissions:
        if permission in user_permissions:
            return True

        parent_permission = permission.split(".")[0]
        if parent_permission in user_permissions:
            return True
    return False

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
        if hasattr(view, "get_required_admin_permissions"):
            required_permission = view.get_required_admin_permissions()
        else:
            required_permission = getattr(view, "required_admin_permission", None)

        if not required_permission:
            return is_admin_dashboard_user(request.user)
        return has_admin_dashboard_permission(request.user, required_permission)
