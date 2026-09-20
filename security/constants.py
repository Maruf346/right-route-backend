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
    OTHER = "OTHER", "Other"


# Human-readable descriptions shown in the form below the Request Type dropdown.
REQUEST_TYPE_DESCRIPTIONS = {
    RequestType.EXPORT: (
        "The customer is requesting a copy of the personal information RightRoute maintains "
        "about their account. Once approved, RightRoute will create a ZIP package containing "
        "the available data in PDF, CSV, and JSON formats. The export will be provided securely "
        "to the verified email address associated with the account."
    ),
    RequestType.DELETE: (
        "The customer is requesting deletion of personal information associated with their "
        "RightRoute account where deletion is permitted. The account will be deactivated, and "
        "eligible profile, permit, route, support, and related records will be removed. Certain "
        "limited records may be retained where required by law, necessary for fraud prevention, "
        "accounting, security, dispute handling, or another approved retention purpose."
    ),
    RequestType.ANONYMIZE: (
        "The customer is requesting that RightRoute permanently remove or transform identifying "
        "information connected with their records. Information that can no longer reasonably be "
        "associated with the customer may remain for aggregate analytics, operational reporting, "
        "and system improvement."
    ),
    RequestType.DELETE_ANONYMIZE: (
        "The customer is requesting that RightRoute delete personal information that is no longer "
        "required and permanently remove identifying information from records retained for approved "
        "analytics, legal, security, accounting, or operational purposes."
    ),
}
