from django.db import models
from core.common_models import BaseModel
from account.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from core.constants import NotifyLogAction, LogStatus
    

class Notification(BaseModel):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="send_notification", blank=True, null=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification", blank=True, null=True)
    action = models.CharField(max_length=255, choices=NotifyLogAction.choices, default=NotifyLogAction.GET)
    
    # title
    # severity
    # priority
        
    message = models.CharField(max_length=255, blank=True, null=True)
    metadata_json = models.JSONField(default=dict)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField()

    entity_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, blank=True, null=True)
    entity_id = models.PositiveIntegerField(blank=True, null=True)
    service = GenericForeignKey('entity_type', 'entity_id')

    @property
    def notify_text(self):
        return f"{self.receiver.first_name} {self.receiver.last_name if self.receiver.last_name else ''} {self.action} at {self.created_at}"

    def __str__(self):
        return f"{self.receiver.first_name} {self.receiver.last_name if self.receiver.last_name else ''} {self.action} at {self.created_at}"



class ActivityLog(BaseModel):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255, choices=NotifyLogAction.choices, default=NotifyLogAction.GET)
    message = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=LogStatus.choices, default=LogStatus.SUCCESS)
    
    entity_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, blank=True, null=True)
    entity_id = models.PositiveBigIntegerField(blank=True, null=True)
    service = GenericForeignKey('entity_type', 'entity_id')
    
    ip_address = models.GenericIPAddressField()
    device_info = models.CharField(max_length=255, blank=True, null=True)
    metadata_json = models.JSONField(default=dict)
    
    def __str__(self):
        username = self.user.username if self.user else None
        return f"{self.created_at} - {username} - {self.action} | {self.status}"

