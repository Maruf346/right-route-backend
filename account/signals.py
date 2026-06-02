from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Team

@receiver(post_save, sender=User)
def create_user_team(sender, instance, created, **kwargs):
    if created:
        Team.objects.get_or_create(
            owner=instance,
            defaults={
                "name": f"{instance.email}'s Team",
            },
        )

