from django.db import models

class UserType(models.TextChoices):
    ADMIN = "ADMIN"
    MAIN_USER = "MAIN_USER"

class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"

class OTPPurpose(models.TextChoices):
    LOGIN = "LOGIN"
    REGISTER = "REGISTER"
    RESET = "RESET"

class TeamMemberStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    SUSPENDED = "SUSPENDED"

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
    REFUND = "REFUND"
    CANCEL = "CANCEL"

class PaymentStatus(models.TextChoices):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

# Route APP-------
class RouteStatus(models.TextChoices):
    DRAFT = "DRAFT"
    ON_GOING = "ON_GOING"
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
class NotifyType(models.TextChoices):
    GET = "GET"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
