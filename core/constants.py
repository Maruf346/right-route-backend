from django.db import models

class UserType(models.TextChoices):
    ADMIN = "ADMIN"
    MAIN_USER = "MAIN_USER"

class CurrentPlanType(models.TextChoices):
    NONE = "NONE", "No Plan"
    INDIVIDUAL = "INDIVIDUAL", "Individual Plan"
    TEAM_MANAGER = "TEAM_MANAGER", "Team Manager"
    TEAM_MEMBER = "TEAM_MEMBER", "Team Member"

class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"

class OTPPurpose(models.TextChoices):
    LOGIN = "LOGIN"
    REGISTER = "REGISTER"
    RESET = "RESET"

class TeamMemberStatus(models.TextChoices):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    SUSPENDED = "SUSPENDED"

class TeamMemberInviteStatus(models.TextChoices):
    PENDING = "PENDING"
    ACCEPT = "ACCEPT"
    EXPIRED = "EXPIRED"

class PaymentMethodType(models.TextChoices):
    CARD = "CARD"
    BANK = "BANK"
    WALLET = "WALLET"

# Subscription APP-------
class PlanType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"

class BillingType(models.TextChoices):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"

class UserSubscriptionStatus(models.TextChoices):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    PAST_DUE = "PAST_DUE"
    FAILED = "FAILED"
    TRIAL = "TRIAL"
    GRACE_PERIOD = "GRACE_PERIOD"

class PaymentStatus(models.TextChoices):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUND_PROCESSING = "REFUND_PROCESSING"
    REFUNDED = "REFUNDED"

class PaymentTransactionStatus(models.TextChoices):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

# Route APP-------
class RouteStatus(models.TextChoices):
    DRAFT = "DRAFT"
    ON_GOING = "ON_GOING"
    START = "START"
    STOP = "STOP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class AIProcessingStatus(models.TextChoices):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class PermitProcessingStatus(models.TextChoices):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class WaypointType(models.TextChoices):
    START = "START"
    STOP = "STOP"
    END = "END"
    CHECKPOINT = "CHECKPOINT"

# Notification APP---
class NotifyLogAction(models.TextChoices):
    GET = "GET"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

class LogStatus(models.TextChoices):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

# Core APP---
class MailConfigType(models.TextChoices):
    SMTP = "smtp"
    API = "api"

