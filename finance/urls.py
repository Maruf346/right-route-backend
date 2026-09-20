from django.urls import path, include
from rest_framework.routers import DefaultRouter
from finance.views import (
    SubscriptionPaymentsSummaryView,
    FleetPaymentsSummaryView,
    FleetPaymentsListView,
    ExpenseViewSet,
    ExpenseSummaryView,
    ExpenseExportView,
)

router = DefaultRouter()
router.register(r"expenses", ExpenseViewSet, basename="finance-expenses")

urlpatterns = [
    # Subscription payments summary
    path("subscription-payments/summary/", SubscriptionPaymentsSummaryView.as_view(), name="subscription-payments-summary"),

    # Fleet payments summary & list
    path("fleet-payments/summary/", FleetPaymentsSummaryView.as_view(), name="fleet-payments-summary"),
    path("fleet-payments/list/", FleetPaymentsListView.as_view(), name="fleet-payments-list"),

    # Expense summary & export (before <pk> router patterns)
    path("expenses/summary/", ExpenseSummaryView.as_view(), name="expenses-summary"),
    path("expenses/download/", ExpenseExportView.as_view(), name="expenses-download"),

    # Expenses CRUD
    path("", include(router.urls)),
]
