from .models import Route, PermitWaypoint, RoutePermit
from rest_framework import serializers
from django.db import transaction
from subscription.services.validators import RouteAccessValidator
from rest_framework.exceptions import ValidationError
from django.db.models import Max
from .service import get_intersection_lat_lng, extract_route_data, normalize_state_code
from account.models import TeamMember

class RouteListSerializer(serializers.ModelSerializer):
    permit_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Route
        fields = ["id", "name", "status", "is_completed", "permit_count", "created_at"]
    
    def get_permit_count(self, obj):
        return obj.permits.count()

class WaypointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermitWaypoint
        fields = "__all__"
        read_only_fields = ["id", "permit", "created_at"]

class RoutePermitSerializer(serializers.ModelSerializer):
    waypoints = WaypointSerializer(many=True, read_only=True)

    class Meta:
        model = RoutePermit
        fields = [
            "id", "index", "name", "permit_number", "issuing_state",
            "start_location", "start_latitude", "start_longitude",
            "end_location", "end_latitude", "end_longitude",
            "permit_file", "permit_text", "extracted_text", "waypoints"
        ]
    
    def get_permit_file(self, obj):
        request = self.context.get("request")
        if obj.permit_file:
            if request:
                return request.build_absolute_uri(obj.permit_file.url)
            return obj.permit_file.url
        return None

class RouteDetailSerializer(serializers.ModelSerializer):
    permits = RoutePermitSerializer(many=True, read_only=True)
    permit_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Route

        fields = [
            "id", "name", "description",
            "status", "is_completed", "permit_count",
            "permits",
        ]
    
    def get_permit_count(self, obj):
        return obj.permits.count()

def _has_permit_input(permit_file=None, permit_text=None):
    """Return True when an actual permit file or non-placeholder permit text is provided."""
    if permit_file:
        return True
    if not permit_text:
        return False
    normalized = str(permit_text).strip().lower()
    return bool(normalized and normalized != "manual route")


def _build_waypoint_objects(route_data, permit, route):
    """Convert extracted route intersections into unsaved PermitWaypoint instances."""
    intersections = (route_data or {}).get("intersection") or []
    start_coords = (permit.start_latitude, permit.start_longitude)
    end_coords = (permit.end_latitude, permit.end_longitude)
    waypoints = (
        get_intersection_lat_lng(
            intersections,
            start_coords=start_coords,
            end_coords=end_coords,
            state_hint=permit.issuing_state,
        )
        if intersections
        else []
    )

    waypoint_objects = []
    for index, wp in enumerate(waypoints, start=1):
        if wp.get("lat") is not None and wp.get("lng") is not None:
            waypoint_objects.append(
                PermitWaypoint(
                    permit=permit,
                    route=route,
                    index=index,
                    name=wp.get("name") or f"Waypoint {index}",
                    latitude=wp.get("lat"),
                    longitude=wp.get("lng"),
                )
            )
    return waypoint_objects


# Route Create with Permit---
class RouteCreateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    start_location = serializers.CharField()
    start_latitude = serializers.FloatField()
    start_longitude = serializers.FloatField()
    end_location = serializers.CharField()
    end_latitude = serializers.FloatField()
    end_longitude = serializers.FloatField()
    permit_file = serializers.FileField(required=False, allow_null=True)
    permit_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    permit_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    issuing_state = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    def validate(self, attrs):
        # Permit file and text are optional; drivers can manually set waypoints
        if attrs.get("issuing_state"):
            state_code = normalize_state_code(attrs["issuing_state"])
            if not state_code:
                raise serializers.ValidationError({"issuing_state": "Use a valid US state."})
            attrs["issuing_state"] = state_code
        return attrs
    
    def create_permit(self, validated_data, route):
        validated_data.pop("name", None)
        permit = RoutePermit.objects.create(
            route=route, index=1,
            **validated_data
        )
        return permit
    
    def get_waypoints(self, validated_data, permit, route):
        permit_file = validated_data.get("permit_file", None)
        permit_text = validated_data.get("permit_text", None)
        if not _has_permit_input(permit_file=permit_file, permit_text=permit_text):
            return []
        route_data = extract_route_data(
            permit_file=permit_file,
            permit_text=permit_text,
            state_hint=permit.issuing_state,
        )
        return _build_waypoint_objects(route_data, permit, route)
    
    def create(self, validated_data):
        request = self.context["request"]
        is_valid, context = RouteAccessValidator.validate_route_creation(request.user)
        team = context["team"]
        
        with transaction.atomic():
            name = validated_data.get("name", None)
            if name is None:
                name = f"{validated_data.get("start_location", "")} to {validated_data.get("end_location", "")}"
            route = Route.objects.create(
                created_by=request.user,
                team=team,
                name=name
            )
            permit = self.create_permit(validated_data, route)
            PermitWaypoint.objects.bulk_create(self.get_waypoints(validated_data, permit, route))
            return route

class PermitSerializers(serializers.ModelSerializer):
    waypoints = WaypointSerializer(many=True, read_only=True)
    start_location = serializers.CharField(required=True)
    end_location = serializers.CharField(required=True)
    permit_file = serializers.FileField(required=False, allow_null=True)
    permit_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = RoutePermit
        fields = [
            "id", "index", "name", "permit_number", "issuing_state",
            "start_location", "start_latitude", "start_longitude", "end_location", "end_latitude", "end_longitude",
            "permit_file", "permit_text", "extracted_text", "waypoints"
        ]
        read_only_fields = ["id", "route", "index", "total_distance"]
    
    def get_permit_file(self, obj):
        request = self.context.get("request")
        if obj.permit_file:
            if request:
                return request.build_absolute_uri(obj.permit_file.url)
            return obj.permit_file.url
        return None
    
    def validate(self, attrs):
        # Permit file or text are optional per client requirements
        if attrs.get("issuing_state"):
            state_code = normalize_state_code(attrs["issuing_state"])
            if not state_code:
                raise serializers.ValidationError({"issuing_state": "Use a valid US state."})
            attrs["issuing_state"] = state_code
        return attrs
    
    def create(self, validated_data):
        route = validated_data.get('route')
        permit_file = validated_data.get('permit_file', None)
        permit_text = validated_data.get('permit_text', None)
        max_index_agg = RoutePermit.objects.filter(route=route).aggregate(Max('index'))
        current_max = max_index_agg['index__max']
        next_index = (current_max or 0) + 1
        validated_data['index'] = next_index
        if not validated_data.get('name'):
            validated_data['name'] = f"Permit {next_index}"
        
        with transaction.atomic():
            permit = super().create(validated_data)
            if _has_permit_input(permit_file=permit_file, permit_text=permit_text):
                try:
                    route_data = extract_route_data(
                        permit_file=permit_file,
                        permit_text=permit_text,
                        state_hint=permit.issuing_state,
                    )
                except Exception as e:
                    print(f"Error extracting route data for subsequent permit: {e}")
                    route_data = None
                waypoint_objects = _build_waypoint_objects(route_data, permit, route)
                if waypoint_objects:
                    PermitWaypoint.objects.bulk_create(waypoint_objects)
            return permit
    
    def update(self, instance, validated_data):
        permit_file = validated_data.get('permit_file', None)
        permit_text = validated_data.get('permit_text', None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if _has_permit_input(permit_file=permit_file, permit_text=permit_text):
                instance.waypoints.all().delete()
                try:
                    route_data = extract_route_data(
                        permit_file=permit_file,
                        permit_text=permit_text,
                        state_hint=instance.issuing_state,
                    )
                except Exception as e:
                    print(f"Error extracting route data for permit update: {e}")
                    route_data = None
                waypoint_objects = _build_waypoint_objects(route_data, instance, instance.route)
                if waypoint_objects:
                    PermitWaypoint.objects.bulk_create(waypoint_objects)
            return instance


class RouteBulkDeleteSerializer(serializers.Serializer):
    route_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)

class AdminRouteHistoryListSerializer(serializers.ModelSerializer):
    route_number = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    driver_email = serializers.EmailField(source="created_by.email")
    account_type = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()
    fleet_name = serializers.SerializerMethodField()
    created_at_formatted = serializers.SerializerMethodField()
    permit_count = serializers.SerializerMethodField()

    class Meta:
        model = Route
        fields = [
            "id",
            "route_number",
            "name",
            "driver_name",
            "driver_email",
            "account_type",
            "team_name",
            "fleet_name",
            "created_at",
            "created_at_formatted",
            "status",
            "is_completed",
            "total_distance_km",
            "total_waypoints",
            "permit_count",
        ]

    def get_route_number(self, obj):
        return f"RR-{obj.created_at.year if obj.created_at else '0000'}-{obj.id:06d}"

    def get_driver_name(self, obj):
        user = obj.created_by
        if obj.team_id:
            membership = TeamMember.objects.filter(team_id=obj.team_id, user=user).first()
            if membership and membership.username:
                return membership.username

        full_name = ""
        profile = getattr(user, "admin_profile", None)
        if profile and profile.full_name:
            full_name = profile.full_name
        return full_name or user.email.split("@")[0]

    def get_account_type(self, obj):
        if obj.team_id:
            return "team"
        return "single"

    def get_team_name(self, obj):
        return obj.team.name if obj.team else None

    def get_fleet_name(self, obj):
        return None

    def get_created_at_formatted(self, obj):
        return obj.created_at.strftime("%b %d, %Y") if obj.created_at else ""

    def get_permit_count(self, obj):
        permit_count = getattr(obj, "permit_count", None)
        if permit_count is not None:
            return permit_count
        return obj.permits.count()


class AdminRoutePermitBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoutePermit
        fields = [
            "id",
            "index",
            "name",
            "start_location",
            "start_latitude",
            "start_longitude",
            "end_location",
            "end_latitude",
            "end_longitude",
            "processing_status",
            "confidence_score",
        ]


class AdminRouteHistoryDetailSerializer(AdminRouteHistoryListSerializer):
    description = serializers.CharField(allow_blank=True, allow_null=True)
    created_by_id = serializers.IntegerField(source="created_by.id")
    team_id = serializers.IntegerField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    route_progress_percentage = serializers.CharField(allow_blank=True, allow_null=True)
    current_waypoint_index = serializers.CharField(allow_blank=True, allow_null=True)
    permit_count = serializers.SerializerMethodField()
    permits = AdminRoutePermitBasicSerializer(many=True, read_only=True)

    class Meta(AdminRouteHistoryListSerializer.Meta):
        fields = AdminRouteHistoryListSerializer.Meta.fields + [
            "description",
            "created_by_id",
            "team_id",
            "started_at",
            "completed_at",
            "cancelled_at",
            "route_progress_percentage",
            "current_waypoint_index",
            "estimated_duration",
            "permits",
        ]


class AdminRouteWaypointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermitWaypoint
        fields = [
            "id",
            "index",
            "name",
            "latitude",
            "longitude",
            "waypoint_type",
            "eta_minutes",
            "description",
            "icon",
        ]


