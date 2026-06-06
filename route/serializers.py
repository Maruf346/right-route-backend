from rest_framework import serializers
from django.db.models import Max
from .models import Route, RoutePermit, PermitWaypoint
from rest_framework.exceptions import ValidationError
import requests
import os
from django.db import transaction
from subscription.services.validators import RouteAccessValidator

class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ["id", "name", "description", "status", "total_distance_km", "estimated_duration", "started_at", "completed_at", "cancelled_at", "route_progress_percentage"]
        read_only_fields = ("status", "total_distance_km", "estimated_duration", "started_at", "completed_at", "cancelled_at", "route_progress_percentage")

class RouteCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Route
        fields = ("name", "description")
    
    def validate(self, attrs):
        request = self.context["request"]
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            request = self.context["request"]
            is_valid, context = RouteAccessValidator.validate_route_creation(request.user)
            team = context["team"]
            
            return Route.objects.create(
                created_by=request.user,
                team=team,
                **validated_data
            )

class RoutePermitSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoutePermit
        fields = [
            "id", "index", "name",
            "start_location", "start_latitude", "start_longitude", "end_location", "end_latitude", "end_longitude",
            "permit_file", "permit_text", "extracted_text", "waypoints"
        ]
        read_only_fields = ["id", "route", "index", "total_distance"]

class RouteDetailSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email",read_only=True)
    permits = RoutePermitSerializer(many=True, read_only=True)
    
    class Meta:
        model = Route
        fields = ["id", "created_by_email", "name", "description", "status", "total_distance_km", "estimated_duration", "started_at", "completed_at", "cancelled_at", "route_progress_percentage", "permits"]
        read_only_fields = ("status", "total_distance_km", "estimated_duration", "started_at", "completed_at", "cancelled_at", "route_progress_percentage")


# =================== Route Permits =================
class WaypointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermitWaypoint
        fields = "__all__"
        read_only_fields = ["id", "permit", "created_at"]

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
    
    def extract_route_data(self, permit_file):
        url = "http://16.192.4.30:8001/api/ocr/extract"

        permit_file.seek(0)
        payload = {
            "file": (
                permit_file.name,
                permit_file.read(),
                permit_file.content_type
            )
        }
        try:
            response = requests.post(
                url,
                files=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            response_data = response.json()
            
            if not response_data.get('success') and not response_data.get('route_information'):
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            return response_data.get('route_information')

        except requests.exceptions.Timeout:
            raise ValidationError(
                "OCR server timeout."
            )
        except requests.exceptions.ConnectionError:
            raise ValidationError(
                "Cannot connect to OCR server."
            )
        except Exception as e:
            raise ValidationError(str(e))
    
    def get_intersection_lat_lng(self, address_list: list):
        address_list_lat_lng = []
        for address in address_list:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": address,
                "key": os.getenv("google_map_api_key")
            }
            response = requests.get(url, params=params)
            data = response.json()
            if data["status"] == "OK":
                location = data["results"][0]["geometry"]["location"]
                address_lat_lng = {
                    "name": address,
                    "lat": location['lat'],
                    "lng": location['lng']
                }
                address_list_lat_lng.append(address_lat_lng)
        return address_list_lat_lng
    
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
            route_data = self.extract_route_data(permit_file)
            print("all intersection: ", route_data['intersection'][:-1])
            waypoints = self.get_intersection_lat_lng(route_data['intersection'][:-1])
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
                route_data = self.extract_route_data(permit_file)
                if not route_data:
                    raise ValidationError("Failed to extract route data.")

                intersections = route_data.get('intersection', [])
                waypoints = self.get_intersection_lat_lng(intersections)
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




