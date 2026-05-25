from django.contrib import admin
from .models import Notification, ActivityLog

admin.site.register(Notification)
admin.site.register(ActivityLog)
