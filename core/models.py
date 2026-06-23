from django.db import models

# Create your models here.
class AIExtractResponse(models.Model):
    response_json = models.JSONField(default=dict)
    response_text = models.TextField(blank=True, null=True)
    create_at = models.DateTimeField(auto_now=True)
