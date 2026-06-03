from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Team
from core.constants import UserType

@receiver(post_save, sender=User)
def create_user_team(sender, instance, created, **kwargs):
    if created and instance.user_type == UserType.MAIN_USER:
        Team.objects.get_or_create(
            owner=instance,
            defaults={
                "name": f"{instance.email}'s Team",
            },
        )

