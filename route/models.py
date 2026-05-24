from django.db import models
from django.conf import settings
# from django.contrib.gis.db import models as gis_moelds
from core.common_models import BaseModel
from account.models import Team, User
from core.constants import AIProcessingStatus, RouteStatus, PermitProcessingStatus, WaypointType


class Route(BaseModel):
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="routes")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="routes")

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    route_status = models.CharField(max_length=20, choices=RouteStatus.choices, default=RouteStatus.DRAFT)
    ai_processing_status = models.CharField(max_length=20, choices=AIProcessingStatus.choices, default=AIProcessingStatus.PENDING)

    total_distance_km = models.FloatField(default=0)
    estimated_duration = models.PositiveIntegerField(default=0)

    total_waypoints = models.PositiveIntegerField(default=0)
    # route_geometry = gis_moelds.LineStringField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    route_progress_percentage = models.CharField(max_length=255, blank=True, null=True)
    current_waypoint_index = models.CharField(max_length=255, blank=True, null=True)
    is_rerouted = models.CharField(max_length=255, blank=True, null=True)
    reroute_count = models.CharField(max_length=255, blank=True, null=True)
    route_health_score = models.CharField(max_length=255, blank=True, null=True)
    risk_score = models.CharField(max_length=255, blank=True, null=True)
    compliance_score = models.CharField(max_length=255, blank=True, null=True)
    ai_summary = models.CharField(max_length=255, blank=True, null=True)
    incident_detected = models.CharField(max_length=255, blank=True, null=True)
    last_tracking_received_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["route_status"]),
            models.Index(fields=["created_by"]),
        ]

    def __str__(self):
        return self.title

class RoutePermit(BaseModel):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="permits")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    index = models.PositiveIntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    
    start_location = models.CharField(max_length=255, blank=True, help_text="Start Location Name")
    start_latitude = models.FloatField(help_text="Start location - Latitude")
    start_longitude = models.FloatField(help_text="Start location - Longitude")
    
    end_location = models.CharField(max_length=255, blank=True, help_text="End Location Name")
    end_latitude = models.FloatField(help_text="End location - Latitude")
    end_longitude = models.FloatField(help_text="End location - Longitude")

    document = models.FileField(upload_to="permits/", blank=True, null=True, help_text="Imported File (PDF/Image)")
    document_text = models.TextField(blank=True, null=True)
    extracted_text = models.TextField(blank=True, null=True)
    ai_response_json = models.JSONField(default=dict)
    processing_status = models.CharField(max_length=20, choices=PermitProcessingStatus.choices, default=PermitProcessingStatus.PENDING)
    
    
    processing_started_at = models.DateTimeField()
    processing_completed_at = models.DateTimeField()
    processing_error = models.JSONField(default=dict)
    confidence_score = models.CharField(max_length=20, default=50)
    
    class Meta:
        ordering = ['route', 'index']
        unique_together = [['route', 'index']]
        indexes = [
            models.Index(fields=['route', 'index']),
        ]

class PermitWaypoint(BaseModel):
    permit = models.ForeignKey(RoutePermit, on_delete=models.CASCADE, related_name="waypoints",)
    index = models.PositiveIntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, help_text="Waypoints Name (like as: 'Exit 340')")
    waypoint_type = models.CharField(max_length=20, choices=WaypointType.choices, default=WaypointType.CHECKPOINT)
    latitude = models.FloatField(help_text="Latitude")
    longitude = models.FloatField(help_text="Longitude")
    description = models.TextField(blank=True, null=True, help_text="Waypoint Details")
    icon = models.CharField(max_length=50, default="📍")
    
    eta_minutes = models.PositiveIntegerField(default=0)
    metadata_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['permit', 'index']
        unique_together = [['permit', 'index']]
        indexes = [
            models.Index(fields=['permit', 'index']),
        ]
    
    def __str__(self):
        return f"{self.permit.name} - {self.index}. {self.name}"



class RouteHistory(BaseModel):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="histories",)
    previous_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,)
    notes = models.TextField(blank=True, null=True)

class RouteTracking(BaseModel):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="trackings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="route_tracking")
    location = models.CharField()
    speed = models.FloatField(default=0)
    heading = models.FloatField(default=0)
    accuracy = models.FloatField(default=0)
    tracked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tracked_at"]),
        ]

