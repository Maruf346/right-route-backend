from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0009_adminuserprofile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="teammemberinvite",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("ACCEPT", "Accept"),
                    ("REJECT", "Reject"),
                    ("EXPIRED", "Expired"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("QUEUED", "Queued"),
                    ("SENDING", "Sending"),
                    ("SENT", "Sent"),
                    ("FAILED", "Failed"),
                ],
                db_index=True,
                default="SENT",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="teammemberinvite",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("QUEUED", "Queued"),
                    ("SENDING", "Sending"),
                    ("SENT", "Sent"),
                    ("FAILED", "Failed"),
                ],
                db_index=True,
                default="QUEUED",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="queued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="invite_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="last_delivery_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="delivery_attempt_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="teammemberinvite",
            name="delivery_failure_detail",
            field=models.TextField(blank=True, default=""),
        ),
    ]
