from django.db import models


class TeamDashboardRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin (Owner)"
    ADMIN = "ADMIN", "Team Admin"
    MEMBER = "MEMBER", "Team Member (Driver)"


TEAM_DASHBOARD_PERMISSIONS = [
    # MANAGE
    "manage.email_password",
    "manage.admin_users",
    "manage.team_users",
    "manage.team_route_history",
    "manage.plan",

    # SUPPORT
    "support.contact_support",
    "support.submit_ticket",
    "support.resources",

    # LEGAL
    "legal.privacy_policy",
    "legal.terms_of_use",
    "legal.disclaimer",

    # SECURITY
    "security.logout",
    "security.data_protection",
    "security.delete_account",
]
