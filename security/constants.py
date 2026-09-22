from django.db import models


class DataRequestStatus(models.TextChoices):
    NEW = "NEW", "New"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
    COMPLETED = "COMPLETED", "Completed"


class RequestType(models.TextChoices):
    EXPORT = "EXPORT", "Export User Data"
    DELETE = "DELETE", "Delete User Data"
    ANONYMIZE = "ANONYMIZE", "Anonymize User Data"
    DELETE_ANONYMIZE = "DELETE_ANONYMIZE", "Delete and Anonymize Retained Data"


class RequestSource(models.TextChoices):
    PHONE = "PHONE", "Phone"
    EMAIL = "EMAIL", "Email"
    WRITTEN = "WRITTEN", "Written Request"
    TEAM_DASHBOARD = "TEAM_DASHBOARD", "Team Dashboard"
    OTHER = "OTHER", "Other"


# Human-readable descriptions shown in the form below the Request Type dropdown.
REQUEST_TYPE_DESCRIPTIONS = {
    RequestType.EXPORT: (
        "You are requesting a copy of the personal information RightRoute maintains "
        "about your account. Once approved, RightRoute will create a ZIP package containing "
        "the available data in PDF, CSV, and JSON formats. The export will be provided securely "
        "to the verified email address associated with the account."
    ),
    RequestType.DELETE: (
        "You are requesting deletion of personal information associated with your "
        "RightRoute account where deletion is permitted. The account will be deactivated, and "
        "eligible profile, permit, route, support, and related records will be removed. Certain "
        "limited records may be retained where required by law, necessary for fraud prevention, "
        "accounting, security, dispute handling, or another approved retention purpose."
    ),
    RequestType.ANONYMIZE: (
        "You are requesting that RightRoute permanently remove or transform identifying "
        "information connected with your records. Information that can no longer reasonably be "
        "associated with you may remain for aggregate analytics, operational reporting, "
        "and system improvement."
    ),
    RequestType.DELETE_ANONYMIZE: (
        "You are requesting that RightRoute delete personal information that is no longer "
        "required and permanently remove identifying information from records retained for approved "
        "analytics, legal, security, accounting, or operational purposes."
    ),
}

# Plan choices for Team Data Protection form
TEAM_DATA_PROTECTION_PLAN_CHOICES = ["Team", "Fleet"]

# Delete account cancellation info per 04 Team dash security section.pdf
DELETE_ACCOUNT_INFO = {
    "team_plan": {
        "title": "Team Plan Subscribers",
        "instructions": [
            "IMPORTANT: If you delete this account in this app's Account Manager before canceling your subscription in the app store, your subscription billing will still continue and you will lose app login access and all of your data including Route History.",
            "You need to first cancel your subscription in the app store.",
            "When you have canceled your subscription, the routing features of this app will be inactive but you will still have access to your Route History and Settings until you delete this account. You will no longer be billed.",
            "IMPORTANT: If you purchased a single user Yearly plan, your subscription will terminated at the end of its billing cycle. We don't offer refunds for unused months.",
            "Please be sure to cancel your paid subscription at the app store you purchased it from.",
        ],
    },
    "fleet_plan": {
        "title": "Fleet Plan Customers",
        "instructions": [
            "Please contact us at sales@getrightroute.app to close your account.",
            "Fill out the form on the Data Protection page to request the deletion of the data associated with this account.",
        ],
        "contact_email": "sales@getrightroute.app",
    },
}

