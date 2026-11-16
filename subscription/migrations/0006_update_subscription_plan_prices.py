from decimal import Decimal
from django.db import migrations

UPDATED_PRICES = {
    "rr_individual_annual": {
        "price": Decimal("149.99"),
        "features_json": {
            "badge": "Save 30%",
            "trial_days": 7,
            "description": "Start your 7-day free trial and begin automating your routes. Cancel anytime.",
        },
    },
    "rr_individual_monthly": {
        "price": Decimal("17.99"),
        "features_json": {
            "trial_days": 7,
            "description": "Start your 7-day free trial and begin automating your routes. Cancel anytime.",
        },
    },
    "rr_team_5_monthly": {
        "price": Decimal("79.00"),
        "features_json": {"trial_days": 7, "drivers": 5},
    },
    "rr_team_10_monthly": {
        "price": Decimal("139.00"),
        "features_json": {"trial_days": 7, "drivers": 10},
    },
    "rr_team_25_monthly": {
        "price": Decimal("279.00"),
        "features_json": {"trial_days": 7, "drivers": 25},
    },
    "rr_team_50_monthly": {
        "price": Decimal("499.00"),
        "features_json": {"trial_days": 7, "drivers": 50},
    },
    "rr_team_100_monthly": {
        "price": Decimal("849.00"),
        "features_json": {"trial_days": 7, "drivers": 100},
    },
}


def update_plan_prices(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscription", "SubscriptionPlan")
    for product_id, data in UPDATED_PRICES.items():
        SubscriptionPlan.objects.filter(product_id=product_id).update(
            price=data["price"],
            features_json=data["features_json"],
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("subscription", "0005_subscriptionplan_trial_days_and_seed_plans"),
    ]

    operations = [
        migrations.RunPython(update_plan_prices, noop_reverse),
    ]
