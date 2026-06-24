from .models import Route, PermitWaypoint, RoutePermit
from rest_framework import serializers
from django.db import transaction
from subscription.services.validators import RouteAccessValidator
from rest_framework.exceptions import ValidationError
from django.db.models import Max
import requests
import os
from core.models import AIExtractResponse
from django.conf import settings

class RouteListSerializer(serializers.ModelSerializer):
    permit_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Route
        fields = ["id", "name", "status", "is_completed", "permit_count"]
    
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
    name = serializers.CharField()
    start_location = serializers.CharField()
    start_latitude = serializers.FloatField()
    start_longitude = serializers.FloatField()
    end_location = serializers.CharField()
    end_latitude = serializers.FloatField()
    end_longitude = serializers.FloatField()
    permit_file = serializers.FileField(required=False)
    permit_text = serializers.CharField(required=False)
    
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
                "key": settings.GOOGLE_MAP_API_KEY
                # "key": os.getenv("GOOGLE_MAP_API_KEY")
            }
            # response = requests.get(url, params=params)
            # data = response.json()
            
            response = requests.get(url, params=params)
            AIExtractResponse.objects.create(response_json=str(response))
            data = response.json()
            AIExtractResponse.objects.create(response_json=str(data))
            
            
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
        route_data = self.extract_route_data(permit_file or permit_text)
        intersection = route_data['intersection'][:-1]
        
        waypoints = self.get_intersection_lat_lng(intersection)
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
            route = Route.objects.create(
                created_by=request.user,
                team=team,
                name=validated_data["name"]
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
                "key": settings.GOOGLE_MAP_API_KEY
            }
            response = requests.get(url, params=params)
            AIExtractResponse.objects.create(response_json=str(response))
            data = response.json()
            AIExtractResponse.objects.create(response_json=str(data))
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

