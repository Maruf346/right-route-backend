from django.contrib import admin
from .models import Route, RoutePermit, PermitWaypoint, RouteHistory, RouteTracking

admin.site.register(Route)
admin.site.register(RoutePermit)
admin.site.register(PermitWaypoint)
admin.site.register(RouteHistory)
admin.site.register(RouteTracking)
