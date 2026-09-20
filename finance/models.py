from django.db import models
from core.common_models import BaseModel
from account.models import User
from finance.constants import PaymentMethod, RecurringType


class Expense(BaseModel):
    """
    Represents an expense entry recorded by admin.
    Displayed on the Expenses calendar list and detailed in Expense Log.
    """
    vendor_company = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Vendor / Company",
    )
    date_paid = models.DateField(
        db_index=True,
        verbose_name="Date Paid",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Amount ($)",
    )
    who_paid = models.CharField(
        max_length=255,
        verbose_name="Who Paid?",
    )
    payment_method = models.CharField(
        max_length=50,
        choices=PaymentMethod.choices,
        default=PaymentMethod.MC_CARD,
        verbose_name="Payment Method",
    )
    recurring = models.CharField(
        max_length=50,
        choices=RecurringType.choices,
        default=RecurringType.NO,
        verbose_name="Recurring?",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Description",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_expenses",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_expenses",
    )

    class Meta:
        ordering = ["-date_paid", "-created_at"]
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"

    def __str__(self):
        return f"{self.vendor_company} - ${self.amount} ({self.date_paid})"
