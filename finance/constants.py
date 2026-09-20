from django.db import models


class PaymentMethod(models.TextChoices):
    MC_CARD = "MC Card", "MC Card"
    VISA = "Visa", "Visa"
    CASH = "Cash", "Cash"
    WIRE = "Wire", "Wire"
    BANK_TRANSFER = "Bank Transfer", "Bank Transfer"
    OTHER = "Other", "Other"


class RecurringType(models.TextChoices):
    NO = "No", "No"
    MONTHLY = "Monthly", "Monthly"
    YEARLY = "Yearly", "Yearly"


class PeriodType(models.TextChoices):
    DAY = "day", "Day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
