from decimal import Decimal
from django.db import migrations, models


PLAY_STORE_PLANS = [
    {
        "product_id": "rr_individual_annual",
        "name": "Individual Annual",
        "plan_type": "INDIVIDUAL",
        "billing_type": "YEARLY",
        "team_limit": 1,
        "price": Decimal("119.99"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {
            "badge": "Save 33%",
            "trial_days": 7,
            "description": "Start your 7-day free trial and begin automating your routes. Cancel anytime.",
        },
        "is_active": True,
    },
    {
        "product_id": "rr_individual_monthly",
        "name": "Individual Monthly",
        "plan_type": "INDIVIDUAL",
        "billing_type": "MONTHLY",
        "team_limit": 1,
        "price": Decimal("14.99"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {
            "trial_days": 7,
            "description": "Start your 7-day free trial and begin automating your routes. Cancel anytime.",
        },
        "is_active": True,
    },
    {
        "product_id": "rr_team_5_monthly",
        "name": "Up to 5 Drivers",
        "plan_type": "TEAM",
        "billing_type": "MONTHLY",
        "team_limit": 5,
        "price": Decimal("69.00"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {"trial_days": 7, "drivers": 5},
        "is_active": True,
    },
    {
        "product_id": "rr_team_10_monthly",
        "name": "Up to 10 Drivers",
        "plan_type": "TEAM",
        "billing_type": "MONTHLY",
        "team_limit": 10,
        "price": Decimal("119.00"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {"trial_days": 7, "drivers": 10},
        "is_active": True,
    },
    {
        "product_id": "rr_team_25_monthly",
        "name": "Up to 25 Drivers",
        "plan_type": "TEAM",
        "billing_type": "MONTHLY",
        "team_limit": 25,
        "price": Decimal("249.00"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {"trial_days": 7, "drivers": 25},
        "is_active": True,
    },
    {
        "product_id": "rr_team_50_monthly",
        "name": "Up to 50 Drivers",
        "plan_type": "TEAM",
        "billing_type": "MONTHLY",
        "team_limit": 50,
        "price": Decimal("449.00"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {"trial_days": 7, "drivers": 50},
        "is_active": True,
    },
    {
        "product_id": "rr_team_100_monthly",
        "name": "Up to 100 Drivers",
        "plan_type": "TEAM",
        "billing_type": "MONTHLY",
        "team_limit": 100,
        "price": Decimal("749.00"),
        "currency": "USD",
        "trial_days": 7,
        "features_json": {"trial_days": 7, "drivers": 100},
        "is_active": True,
    },
]


def seed_play_store_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscription", "SubscriptionPlan")

    # Preserve existing plan rows referenced by UserSubscription FK when possible
    # (e.g. legacy dummy Monthly plan -> rr_individual_monthly, Test Team Plan -> rr_team_100_monthly)
    legacy_individual = SubscriptionPlan.objects.filter(
        product_id="asr13412dsfasf"
    ).first()
    if legacy_individual and not SubscriptionPlan.objects.filter(product_id="rr_individual_monthly").exists():
        data = next(p for p in PLAY_STORE_PLANS if p["product_id"] == "rr_individual_monthly")
        for field, val in data.items():
            setattr(legacy_individual, field, val)
        legacy_individual.save()

    legacy_team = SubscriptionPlan.objects.filter(
        product_id="asr13412dsfasfqwe12"
    ).first()
    if legacy_team and not SubscriptionPlan.objects.filter(product_id="rr_team_100_monthly").exists():
        data = next(p for p in PLAY_STORE_PLANS if p["product_id"] == "rr_team_100_monthly")
        for field, val in data.items():
            setattr(legacy_team, field, val)
        legacy_team.save()

    for plan_data in PLAY_STORE_PLANS:
        SubscriptionPlan.objects.update_or_create(
            product_id=plan_data["product_id"],
            defaults=plan_data,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("subscription", "0004_purchaseinfo_amount_purchaseinfo_currency_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="trial_days",
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.RunPython(seed_play_store_plans, noop_reverse),
    ]
