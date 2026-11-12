from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("route", "0004_alter_route_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="routepermit",
            name="permit_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="routepermit",
            name="issuing_state",
            field=models.CharField(blank=True, db_index=True, max_length=2, null=True),
        ),
    ]
