from .models import Route, PermitWaypoint, RoutePermit
from rest_framework import serializers
from django.db import transaction
from subscription.services.validators import RouteAccessValidator
from rest_framework.exceptions import ValidationError
from django.db.models import Max
from .service import get_intersection_lat_lng, extract_route_data

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
            "id", "index", "name",
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

# Route Create with Permit---
class RouteCreateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    start_location = serializers.CharField()
    start_latitude = serializers.FloatField()
    start_longitude = serializers.FloatField()
    end_location = serializers.CharField()
    end_latitude = serializers.FloatField()
    end_longitude = serializers.FloatField()
    permit_file = serializers.FileField(required=False)
    permit_text = serializers.CharField(required=False)
    
    def validate(self, attrs):
        if not (attrs.get("permit_file") or attrs.get("permit_text")):
            raise serializers.ValidationError({
                "permit_file": "Permit file or Permit Text must be submitted."
            })
        return attrs
    
    def create_permit(self, validated_data, route):
        validated_data.pop("name")
        permit = RoutePermit.objects.create(
            route=route, index=1,
            **validated_data
        )
        return permit
    
    def get_waypoints(self, validated_data, permit, route):
        permit_file = validated_data.get("permit_file", None)
        permit_text = validated_data.get("permit_text", None)
        route_data = extract_route_data(permit_file=permit_file, permit_text=permit_text)
        intersection = route_data['intersection'][:-1]
        
        waypoints = get_intersection_lat_lng(intersection)
        waypoint_objects = []
        
        for index, wp in enumerate(waypoints, start=1):
            last_wp = PermitWaypoint.objects.filter(permit=permit).last()
            waypoint = PermitWaypoint(
                permit=permit,
                route=route,
                index=index,
                name=wp.get('name', f'Waypoint {index}'),
                latitude=wp.get('lat'),
                longitude=wp.get('lng')
            )
            waypoint_objects.append(waypoint)
        return waypoint_objects
    
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
    permit_file = serializers.FileField(required=True)

    class Meta:
        model = RoutePermit
        fields = [
            "id", "index", "name",
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
        if not attrs.get("permit_file"):
            raise serializers.ValidationError({
                "permit_file": "Permit document must be submitted."
            })
        return attrs
    
    def create(self, validated_data):
        route = validated_data.get('route')
        permit_file = validated_data.get('permit_file')
        max_index_agg = RoutePermit.objects.filter(route=route).aggregate(Max('index'))
        current_max = max_index_agg['index__max']
        validated_data['index'] = (current_max or 0) + 1
        
        with transaction.atomic():
            permit = super().create(validated_data)
            route_data = extract_route_data(permit_file)
            print("all intersection: ", route_data['intersection'][:-1])
            waypoints = get_intersection_lat_lng(route_data['intersection'][:-1])
            waypoint_objects = []
            for index, wp in enumerate(waypoints, start=1):
                last_wp = PermitWaypoint.objects.filter(permit=permit).last()
                waypoint = PermitWaypoint(
                    permit=permit,
                    index=index,
                    name=wp.get('name', f'Waypoint {index}'),
                    latitude=wp.get('lat'),
                    longitude=wp.get('lng')
                )
                waypoint_objects.append(waypoint)
            
            # Bulk create for database efficiency
            PermitWaypoint.objects.bulk_create(waypoint_objects)
            return permit
    
    def update(self, instance, validated_data):
        permit_file = validated_data.get('permit_file', None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if permit_file:
                instance.waypoints.all().delete()
                route_data = extract_route_data(permit_file)
                if not route_data:
                    raise ValidationError("Failed to extract route data.")

                intersections = route_data.get('intersection', [])
                waypoints = get_intersection_lat_lng(intersections)
                if not waypoints:
                    raise ValidationError("No waypoint found.")

                waypoint_objects = []
                for index, wp in enumerate(waypoints, start=1):
                    waypoint = PermitWaypoint(
                        permit=instance,
                        index=index,
                        name=wp.get('name', f'Waypoint {index}'),
                        latitude=wp.get('lat'),
                        longitude=wp.get('lng')
                    )
                    waypoint_objects.append(waypoint)
                PermitWaypoint.objects.bulk_create(waypoint_objects)
            return instance


class RouteBulkDeleteSerializer(serializers.Serializer):
    route_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)


