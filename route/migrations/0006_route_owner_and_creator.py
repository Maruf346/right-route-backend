from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_creator_to_owner(apps, schema_editor):
    Route = apps.get_model("route", "Route")
    Route.objects.filter(user__isnull=True).update(user_id=models.F("created_by_id"))


class Migration(migrations.Migration):
    dependencies = [
        ("route", "0005_routepermit_permit_number_and_issuing_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="route",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="routes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(copy_creator_to_owner, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="route",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="routes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="route",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_routes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="route",
            index=models.Index(fields=["user"], name="route_route_user_id_250198_idx"),
        ),
    ]
