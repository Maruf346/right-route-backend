from django.db import models


class TicketStatus(models.TextChoices):
    NEW = "NEW", "New"
    OPEN = "OPEN", "Open"
    WAITING_CUSTOMER = "WAITING_CUSTOMER", "Waiting for Customer"
    WAITING_INTERNAL = "WAITING_INTERNAL", "Waiting for Internal Team"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"
    DRAFT = "DRAFT", "Draft"


class TicketPriority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TicketSource(models.TextChoices):
    WEBSITE_FORM = "WEBSITE_FORM", "Website Support Form"
    TEAM_DASHBOARD = "TEAM_DASHBOARD", "Team Dashboard Support Form"
    DASHBOARD = "DASHBOARD", "Ticket Creator in Dashboard"
    STAFF_DISCOVERED = "STAFF_DISCOVERED", "Staff-discovered"
    AUTOMATED_ALERT = "AUTOMATED_ALERT", "Automated system alert"


class SupportPlatform(models.TextChoices):
    IPHONE = "iPhone", "iPhone"
    IPOD = "iPod", "iPod"
    ANDROID_PHONE = "Android Phone", "Android Phone"
    ANDROID_TABLET = "Android Tablet", "Android Tablet"
    WEB_DASHBOARD = "Web Dashboard", "Web Dashboard"
    OTHER = "Other", "Other"


class ContactMethod(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    PHONE = "PHONE", "Phone"
    VIDEO_CALL = "VIDEO_CALL", "Video call"
    WEBSITE_FORM = "WEBSITE_FORM", "Website Form"


class PlanType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL", "Individual"
    TEAM = "TEAM", "Team"
    FLEET = "FLEET", "Fleet"
    TRIAL = "TRIAL", "Trial User"


# Support Contact Information as specified in 02 Team dash support section.pdf
SUPPORT_CONTACT_PHONE = "888-603-6317"
SUPPORT_CONTACT_EMAILS = {
    "technical_issues": "help@getrightroute.app",
    "subscription_help": "service@getrightroute.app",
    "fleet_sales": "sales@getrightroute.app",
    "legal": "legal@getrightroute.app",
}
SUPPORT_NOTIFICATION_EMAIL = "help@getrightroute.app"


class MainCategory(models.TextChoices):
    ACCOUNT_LOGIN = "ACCOUNT_LOGIN", "Account and Login Issues"
    BILLING_SUBSCRIPTION = "BILLING_SUBSCRIPTION", "Billing and Subscription Issues"
    PERMIT_PROCESSING = "PERMIT_PROCESSING", "Permit Import and Processing"
    ROUTE_NAVIGATION = "ROUTE_NAVIGATION", "Route and Navigation Issues"
    APP_TECHNICAL = "APP_TECHNICAL", "App Technical Issues"
    TEAM_DRIVER = "TEAM_DRIVER", "Team and Driver Management"
    ACCOUNT_CHANGES = "ACCOUNT_CHANGES", "Account Changes and Requests"
    COMPLAINT = "COMPLAINT", "Complaint or Service Concern"
    FEATURE_REQUEST = "FEATURE_REQUEST", "Feature Request or Suggestion"
    GENERAL_OTHER = "GENERAL_OTHER", "General Question or Other"


CATEGORY_ABBREVIATIONS = {
    MainCategory.ACCOUNT_LOGIN: "Acct/Login",
    MainCategory.BILLING_SUBSCRIPTION: "Billing/Sub",
    MainCategory.PERMIT_PROCESSING: "Perm Import/Proc",
    MainCategory.ROUTE_NAVIGATION: "Route/Nav",
    MainCategory.APP_TECHNICAL: "App Issue",
    MainCategory.TEAM_DRIVER: "Team Mag",
    MainCategory.ACCOUNT_CHANGES: "Acct Changes",
    MainCategory.COMPLAINT: "Complaint",
    MainCategory.FEATURE_REQUEST: "Feature Req",
    MainCategory.GENERAL_OTHER: "Gen Question",
}

CATEGORY_LABEL_TO_KEY = {
    "Account and Login Issues": MainCategory.ACCOUNT_LOGIN,
    "Billing and Subscription Issues": MainCategory.BILLING_SUBSCRIPTION,
    "Permit Import and Processing": MainCategory.PERMIT_PROCESSING,
    "Route and Navigation Issues": MainCategory.ROUTE_NAVIGATION,
    "App Technical Issues": MainCategory.APP_TECHNICAL,
    "Team and Driver Management": MainCategory.TEAM_DRIVER,
    "Account Changes and Requests": MainCategory.ACCOUNT_CHANGES,
    "Complaint or Service Concern": MainCategory.COMPLAINT,
    "Feature Request or Suggestion": MainCategory.FEATURE_REQUEST,
    "General Question or Other": MainCategory.GENERAL_OTHER,
}

SUBCATEGORIES = {
    MainCategory.ACCOUNT_LOGIN: [
        "Cannot log in",
        "Password reset",
        "Email address change",
        "Account not recognized",
        "Driver invitation issue",
        "Team or fleet account access",
        "Account locked or disabled",
        "Other account/login issues",
    ],
    MainCategory.BILLING_SUBSCRIPTION: [
        "Payment failed",
        "Incorrect charge",
        "Duplicate charge",
        "Subscription cancellation",
        "Monthly-to-annual plan change",
        "Free trial issue",
        "Promotional offer or discount issue",
        "Apple App Store billing",
        "Google Play billing",
        "Fleet contract billing",
        "Other billing/subscription issue",
    ],
    MainCategory.PERMIT_PROCESSING: [
        "Permit will not upload",
        "Unsupported PDF",
        "Permit text not recognized",
        "Incorrect route extracted",
        "Missing route instructions",
        "Start or end point not detected",
        "Waypoints placed incorrectly",
        "Processing failed",
        "Duplicate permit",
        "Other import/processing issue",
    ],
    MainCategory.ROUTE_NAVIGATION: [
        "Route is incorrect",
        "Route does not match permit",
        "Missing waypoint",
        "Incorrect road or highway",
        "Navigation will not start",
        "Voice guidance issue",
        "Route recalculation issue",
        "Map display issue",
        "Offline route issue",
        "GPS location issue",
        "Other route/navigation issue",
    ],
    MainCategory.APP_TECHNICAL: [
        "App crashes",
        "App freezes",
        "Page will not load",
        "Button does not work",
        "Slow performance",
        "Installation issue",
        "Update issue",
        "Device compatibility",
        "Notification issue",
        "Internet connection issue",
        "Unknown technical error",
        "Other technical issue",
    ],
    MainCategory.TEAM_DRIVER: [
        "Cannot add driver",
        "Driver invitation not received",
        "Driver cannot activate account",
        "Driver removal issue",
        "Driver limit reached",
        "Incorrect driver access",
        "Team Manager dashboard issue",
        "User role or permission issue",
        "Fleet account setup issue",
        "Other team/driver issue",
    ],
    MainCategory.ACCOUNT_CHANGES: [
        "Update account information",
        "Change company information",
        "Add or remove administrator",
        "Transfer account ownership",
        "Delete account",
        "Request account records",
        "Change plan",
        "Increase driver allowance",
        "Other account issue",
    ],
    MainCategory.COMPLAINT: [
        "App performance complaint",
        "Routing complaint",
        "Billing complaint",
        "Customer service complaint",
        "Feature dissatisfaction",
        "Pricing complaint",
        "Privacy concern",
        "Safety concern",
        "Other concern",
    ],
    MainCategory.FEATURE_REQUEST: [
        "New app feature",
        "Dashboard improvement",
        "Permit-processing improvement",
        "Navigation improvement",
        "Offline functionality",
        "Team-management improvement",
        "Billing improvement",
        "General suggestion",
    ],
    MainCategory.GENERAL_OTHER: [
        "How-to question",
        "Product information",
        "Pricing question",
        "Feedback",
        "Testimonial",
        "Other",
    ],
}

ALLOWED_ATTACHMENT_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "doc", "docx", "txt"]
MAX_ATTACHMENT_SIZE_BYTES = 3 * 1024 * 1024  # 3 MB
MAX_ATTACHMENTS_PER_TICKET = 3
