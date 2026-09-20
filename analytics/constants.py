from django.db import models


class TimePeriodTab(models.TextChoices):
    LAST_30_DAYS = "last_30_days", "Last 30 Days"
    QTD = "qtd", "Quarter to Date"
    YTD = "ytd", "Year to Date"
    CUSTOM = "custom", "Custom Range"


STANDARD_PLAN_NAMES = [
    "Single Monthly",
    "Single Annual",
    "Team 5",
    "Team 10",
    "Team 25",
    "Team 50",
    "Team 100",
    "Fleet",
]
