from django.db import models


class TeamDashboardRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin (Owner)"
    ADMIN = "ADMIN", "Team Admin"
    MEMBER = "MEMBER", "Team Member (Driver)"


TEAM_DASHBOARD_PERMISSIONS = [
    # MANAGE
    "manage.email_password",
    "manage.admin_users",
    "manage.admin_users.add",
    "manage.team_users",
    "manage.route_history.my",
    "manage.route_history.team",
    "manage.plan",

    # SUPPORT
    "support.contact_support",
    "support.help_center",
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

# Structured tree representation for frontend checkboxes
TEAM_PERMISSION_TREE = [
    {
        "key": "manage",
        "label": "Manage",
        "children": [
            {"key": "manage.email_password", "label": "Email / Password"},
            {
                "key": "manage.admin_users",
                "label": "Admin Users",
                "children": [
                    {"key": "manage.admin_users.add", "label": "Add / Edit Admin Users"},
                ],
            },
            {"key": "manage.team_users", "label": "Team Users"},
            {
                "key": "manage.route_history.team",
                "label": "Team Route History (All Drivers)",
            },
            {
                "key": "manage.route_history.my",
                "label": "My Route History (Own Routes Only)",
            },
            {"key": "manage.plan", "label": "Plan"},
        ],
    },
    {
        "key": "support",
        "label": "Support",
        "children": [
            {"key": "support.contact_support", "label": "Contact Support"},
            {"key": "support.help_center", "label": "Help Center"},
            {"key": "support.submit_ticket", "label": "Submit Ticket"},
            {"key": "support.resources", "label": "Resources"},
        ],
    },
    {
        "key": "legal",
        "label": "Legal",
        "children": [
            {"key": "legal.privacy_policy", "label": "Privacy Policy"},
            {"key": "legal.terms_of_use", "label": "Terms of Use"},
            {"key": "legal.disclaimer", "label": "Disclaimer"},
        ],
    },
    {
        "key": "security",
        "label": "Security",
        "children": [
            {"key": "security.logout", "label": "Logout"},
            {"key": "security.data_protection", "label": "Data Protection"},
            {"key": "security.delete_account", "label": "Delete Account"},
        ],
    },
]

