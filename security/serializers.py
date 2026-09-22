"""
Serializers for the Security / Data Protection app.
"""

from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from security.constants import (
    DataRequestStatus,
    REQUEST_TYPE_DESCRIPTIONS,
    RequestSource,
    RequestType,
    TEAM_DATA_PROTECTION_PLAN_CHOICES,
    DELETE_ACCOUNT_INFO,
)
from security.models import DataProtectionRequest, DataRequestNote, generate_request_id


# ─────────────────────────────────────────────────────────────────────────────
# Note serializers
# ─────────────────────────────────────────────────────────────────────────────

class DataRequestNoteSerializer(serializers.ModelSerializer):
    written_by_email = serializers.SerializerMethodField()
    written_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DataRequestNote
        fields = [
            "id",
            "body",
            "written_by_email",
            "written_by_name",
            "is_system_note",
            "created_at",
        ]

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_written_by_email(self, obj):
        return obj.written_by.email if obj.written_by else None

    @extend_schema_field(serializers.CharField())
    def get_written_by_name(self, obj):
        if not obj.written_by:
            return "System"
        profile = getattr(obj.written_by, "admin_profile", None)
        return profile.full_name if profile else obj.written_by.email


class DataRequestNoteCreateSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# List serializers (one per status list in the right column)
# ─────────────────────────────────────────────────────────────────────────────

class DataProtectionRequestListSerializer(serializers.ModelSerializer):
    """
    Lean list representation — used for the three right-column lists.
    Each list shows: customer name+email, request type, and key date.
    """
    request_type_display = serializers.CharField(
        source="get_request_type_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    class Meta:
        model = DataProtectionRequest
        fields = [
            "id",
            "request_id",
            "customer_name",
            "customer_email",
            "request_type",
            "request_type_display",
            "status",
            "status_display",
            "date_requested",
            "approval_email_sent_at",
            "completed_at",
            "created_at",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Detail serializer (full form view)
# ─────────────────────────────────────────────────────────────────────────────

class DataProtectionRequestDetailSerializer(serializers.ModelSerializer):
    """
    Full form representation including notes, computed warnings, button states,
    and request type description.
    """
    notes = DataRequestNoteSerializer(many=True, read_only=True)
    warnings = serializers.SerializerMethodField()
    request_type_description = serializers.SerializerMethodField()
    request_type_display = serializers.CharField(
        source="get_request_type_display", read_only=True
    )
    source_display = serializers.CharField(
        source="get_source_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    # Button states — mirrors the PDF's enabled/disabled logic
    can_save_as_pending = serializers.BooleanField(read_only=True)
    can_perform = serializers.BooleanField(read_only=True)
    can_send_completion_email = serializers.BooleanField(read_only=True)

    approval_email_sent_by_email = serializers.SerializerMethodField()
    performed_by_email = serializers.SerializerMethodField()
    created_by_email = serializers.SerializerMethodField()
    updated_by_email = serializers.SerializerMethodField()

    class Meta:
        model = DataProtectionRequest
        fields = [
            # Identifiers
            "id",
            "request_id",
            "status",
            "status_display",
            "date_requested",
            # Customer
            "customer_email",
            "customer_user",
            "customer_name",
            "plan_type",
            "account_status",
            "account_created_at",
            "phone_number",
            # Computed
            "warnings",
            # Request details
            "source",
            "source_display",
            "source_other_detail",
            "request_type",
            "request_type_display",
            "request_type_description",
            # Approval
            "approval_received",
            "approval_source",
            "approval_received_date",
            "admin_confirmed",
            "approval_email_sent_at",
            "approval_email_sent_by_email",
            # Execution
            "performed_at",
            "performed_by_email",
            "perform_result",
            "completed_at",
            # Export
            "export_zip_size",
            "export_zip_created_at",
            "export_zip_expires_at",
            # Button states
            "can_save_as_pending",
            "can_perform",
            "can_send_completion_email",
            # Audit
            "created_by_email",
            "updated_by_email",
            "created_at",
            "updated_at",
            # Notes
            "notes",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_warnings(self, obj):
        return obj.get_warnings()

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_request_type_description(self, obj):
        return REQUEST_TYPE_DESCRIPTIONS.get(obj.request_type, "")

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_approval_email_sent_by_email(self, obj):
        return obj.approval_email_sent_by.email if obj.approval_email_sent_by else None

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_performed_by_email(self, obj):
        return obj.performed_by.email if obj.performed_by else None

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_created_by_email(self, obj):
        return obj.created_by.email if obj.created_by else None

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_updated_by_email(self, obj):
        return obj.updated_by.email if obj.updated_by else None


# ─────────────────────────────────────────────────────────────────────────────
# Create serializer (SAVE AS NEW button)
# ─────────────────────────────────────────────────────────────────────────────

class DataProtectionRequestCreateSerializer(serializers.ModelSerializer):
    """
    Creates a new Data Protection Request (Save as New).
    The request_id is pre-generated on the client via the generate-id endpoint,
    but we re-validate uniqueness here and regenerate if needed.
    """
    request_id = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = DataProtectionRequest
        fields = [
            "request_id",
            "date_requested",
            "customer_email",
            "customer_user",
            "customer_name",
            "plan_type",
            "account_status",
            "account_created_at",
            "phone_number",
            "source",
            "source_other_detail",
            "request_type",
        ]
        extra_kwargs = {
            "date_requested": {"required": False},
            "customer_user": {"required": False},
            "customer_name": {"required": False},
            "plan_type": {"required": False},
            "account_status": {"required": False},
            "account_created_at": {"required": False},
            "phone_number": {"required": False},
            "source": {"required": False},
            "source_other_detail": {"required": False},
            "request_type": {"required": False},
        }

    def validate_source_other_detail(self, value):
        source = self.initial_data.get("source") or (
            self.instance.source if self.instance else ""
        )
        if source == RequestSource.OTHER and not value:
            raise serializers.ValidationError(
                "Please describe the source when selecting 'Other'."
            )
        return value

    def validate(self, attrs):
        # Ensure unique request_id
        request_id = attrs.get("request_id") or ""
        if not request_id or DataProtectionRequest.objects.filter(request_id=request_id).exists():
            attrs["request_id"] = generate_request_id()
        if not attrs.get("date_requested"):
            attrs["date_requested"] = timezone.now()
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["created_by"] = request.user if request else None
        validated_data["updated_by"] = request.user if request else None
        return super().create(validated_data)


# ─────────────────────────────────────────────────────────────────────────────
# Update serializer (edit form fields after creation)
# ─────────────────────────────────────────────────────────────────────────────

class DataProtectionRequestUpdateSerializer(serializers.ModelSerializer):
    """
    Allows updating editable form fields on an existing request.
    Completed requests cannot be edited.
    """

    class Meta:
        model = DataProtectionRequest
        fields = [
            "date_requested",
            "customer_email",
            "customer_user",
            "customer_name",
            "plan_type",
            "account_status",
            "account_created_at",
            "phone_number",
            "source",
            "source_other_detail",
            "request_type",
            "approval_received",
            "approval_source",
            "approval_received_date",
            "admin_confirmed",
        ]
        extra_kwargs = {f: {"required": False} for f in fields}

    def validate(self, attrs):
        if self.instance and self.instance.status == DataRequestStatus.COMPLETED:
            raise serializers.ValidationError(
                "Completed requests cannot be edited."
            )
        source = attrs.get("source", self.instance.source if self.instance else "")
        other_detail = attrs.get(
            "source_other_detail",
            self.instance.source_other_detail if self.instance else "",
        )
        if source == RequestSource.OTHER and not other_detail:
            raise serializers.ValidationError(
                {"source_other_detail": "Please describe the source when selecting 'Other'."}
            )
        return attrs

    def update(self, instance, validated_data):
        request = self.context.get("request")
        instance.updated_by = request.user if request else None
        return super().update(instance, validated_data)


# ─────────────────────────────────────────────────────────────────────────────
# Find customer serializer
# ─────────────────────────────────────────────────────────────────────────────

class FindCustomerSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class CustomerFoundSerializer(serializers.Serializer):
    """
    Response shape for a successful customer lookup.
    Mirrors what the form auto-fills after clicking FIND.
    """
    found = serializers.BooleanField()
    user_id = serializers.UUIDField(allow_null=True)
    customer_name = serializers.CharField(allow_blank=True)
    verified_email = serializers.EmailField(allow_null=True)
    plan_type = serializers.CharField(allow_blank=True)
    account_status = serializers.CharField(allow_blank=True)
    account_created_at = serializers.DateTimeField(allow_null=True)
    phone_number = serializers.CharField(allow_blank=True)
    message = serializers.CharField(allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# Email customer serializer
# ─────────────────────────────────────────────────────────────────────────────

class EmailCustomerSerializer(serializers.Serializer):
    """
    Request body for the EMAIL CUSTOMER action.
    personal_message is optional — added by the admin before sending.
    """
    personal_message = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1000,
        help_text="Short personalised message the admin can add before sending.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Perform request serializer
# ─────────────────────────────────────────────────────────────────────────────

class PerformRequestSerializer(serializers.Serializer):
    """
    Body for the PERFORM APPROVED REQUEST action.
    The admin confirms the final confirmation dialog before the backend acts.
    """
    confirmed = serializers.BooleanField(
        help_text=(
            "Must be true — represents the admin clicking 'CONFIRM AND PERFORM REQUEST' "
            "in the final confirmation dialog."
        )
    )

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must confirm the action in the dialog before it can be performed."
            )
        return value


# ─────────────────────────────────────────────────────────────────────────────
# Generate ID response serializer
# ─────────────────────────────────────────────────────────────────────────────

class GenerateRequestIdSerializer(serializers.Serializer):
    request_id = serializers.CharField()


# ─────────────────────────────────────────────────────────────────────────────
# Team Dashboard Data Protection Serializers
# ─────────────────────────────────────────────────────────────────────────────

class TeamDataProtectionPrefillSerializer(serializers.Serializer):
    name = serializers.CharField()
    account_email = serializers.EmailField()
    phone_number = serializers.CharField(allow_blank=True)
    plan_type = serializers.CharField()


class RequestTypeOptionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()


class TeamDataProtectionOptionsSerializer(serializers.Serializer):
    plan_choices = serializers.ListField(child=serializers.CharField())
    request_types = RequestTypeOptionSerializer(many=True)


class TeamDataProtectionSubmitSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=255, help_text="First / last name")
    account_email = serializers.EmailField(required=True, help_text="Account email")
    plan_type = serializers.CharField(required=False, default="Team", help_text="Team or Fleet")
    phone_number = serializers.CharField(required=False, allow_blank=True, default="", help_text="Phone number")
    request_type = serializers.ChoiceField(
        choices=RequestType.choices,
        required=True,
        help_text="EXPORT, DELETE, ANONYMIZE, or DELETE_ANONYMIZE",
    )


class TeamDataProtectionRequestItemSerializer(serializers.ModelSerializer):
    request_type_display = serializers.CharField(source="get_request_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DataProtectionRequest
        fields = [
            "id",
            "request_id",
            "request_type",
            "request_type_display",
            "status",
            "status_display",
            "customer_name",
            "customer_email",
            "phone_number",
            "plan_type",
            "date_requested",
            "completed_at",
            "created_at",
        ]


class DeleteAccountInfoSectionSerializer(serializers.Serializer):
    title = serializers.CharField()
    instructions = serializers.ListField(child=serializers.CharField())
    contact_email = serializers.EmailField(required=False)


class TeamDeleteAccountInfoSerializer(serializers.Serializer):
    team_plan = DeleteAccountInfoSectionSerializer()
    fleet_plan = DeleteAccountInfoSectionSerializer()

