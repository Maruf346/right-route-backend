from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from notification.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    entity_type_label = serializers.SerializerMethodField()
    entity_type_model = serializers.SerializerMethodField()
    entity_type_app = serializers.SerializerMethodField()
    entity_display = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "action",
            "action_display",
            "message",
            "status",
            "status_display",
            "entity_type",
            "entity_type_label",
            "entity_type_app",
            "entity_type_model",
            "entity_id",
            "entity_display",
            "ip_address",
            "device_info",
            "metadata_json",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_user_id(self, obj):
        return obj.user_id

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_user_email(self, obj):
        return obj.user.email if obj.user else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_user_name(self, obj):
        if not obj.user:
            return None
        profile = getattr(obj.user, "admin_profile", None)
        if profile and profile.full_name:
            return profile.full_name
        return obj.user.email

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type_label(self, obj):
        if not obj.entity_type:
            return None
        return f"{obj.entity_type.app_label}.{obj.entity_type.model}"

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type_app(self, obj):
        return obj.entity_type.app_label if obj.entity_type else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type_model(self, obj):
        return obj.entity_type.model if obj.entity_type else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_display(self, obj):
        try:
            return str(obj.service) if obj.service else None
        except Exception:
            return None


class ActivityLogOptionItemSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class ActivityLogEntityTypeOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    app_label = serializers.CharField()
    model = serializers.CharField()


class ActivityLogOptionsSerializer(serializers.Serializer):
    actions = ActivityLogOptionItemSerializer(many=True)
    statuses = ActivityLogOptionItemSerializer(many=True)
    entity_types = ActivityLogEntityTypeOptionSerializer(many=True)


class ActivityLogOptionsResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = ActivityLogOptionsSerializer()
