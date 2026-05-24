from django.db import models
from core.common_models import BaseModel
from account.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from core.constants import NotifyType
    

class Notification(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="send_notification", blank=True, null=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification", blank=True, null=True)
    action = models.CharField(max_length=255, choices=NotifyType.choices, default=NotifyType.GET)
    message = models.CharField(max_length=255, blank=True, null=True)
    metadata_json = models.JSONField(default=dict)
    is_read = models.BooleanField(default=False)

    entity_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, blank=True, null=True)
    entity_id = models.PositiveIntegerField(blank=True, null=True)
    service = GenericForeignKey('entity_type', 'entity_id')

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def notify_text(self):
        return f"{self.receiver.first_name} {self.receiver.last_name if self.receiver.last_name else ''} {self.action} at {self.created_at}"

    def __str__(self):
        return f"{self.receiver.first_name} {self.receiver.last_name if self.receiver.last_name else ''} {self.action} at {self.created_at}"


