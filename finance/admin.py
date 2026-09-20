from django.contrib import admin
from finance.models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "vendor_company",
        "date_paid",
        "amount",
        "who_paid",
        "payment_method",
        "recurring",
        "created_at",
    )
    list_filter = ("payment_method", "recurring", "date_paid")
    search_fields = ("vendor_company", "who_paid", "description")
    date_hierarchy = "date_paid"
    readonly_fields = ("created_at", "updated_at")
