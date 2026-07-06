from rest_framework import serializers

class GetStartingWaypiontSerializer(serializers.Serializer):
    location = serializers.CharField(required=True)
