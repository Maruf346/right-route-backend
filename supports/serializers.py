import os
from rest_framework import serializers
from django.utils import timezone
from django.db import transaction

from account.models import User, AdminUserProfile
from supports.constants import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    MAX_ATTACHMENT_SIZE_BYTES,
    MAX_ATTACHMENTS_PER_TICKET,
    MainCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
    ContactMethod,
    CATEGORY_ABBREVIATIONS,
    CATEGORY_LABEL_TO_KEY,
    SUBCATEGORIES,
)
from supports.models import (
    SupportTicket,
    TicketAttachment,
    TicketMessage,
    TicketActivityLog,
)
from supports.utils import (
    generate_ticket_number,
    determine_ticket_priority,
    format_customer_display_name,
    get_category_abbreviation,
    match_customer_account,
    scan_file_for_malware,
)
from supports.emails import (
    send_customer_confirmation_email,
    send_staff_notification_email,
    send_assignment_email,
)


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = [
            "id",
            "file",
            "original_filename",
            "file_size",
            "file_type",
            "uploaded_by",
            "created_at",
        ]
        read_only_fields = ["id", "original_filename", "file_size", "file_type", "uploaded_by", "created_at"]

    def validate_file(self, value):
        ext = os.path.splitext(value.name)[1].lstrip(".").lower()
        if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise serializers.ValidationError(
                f"File type '.{ext}' is not allowed. Allowed types: {', '.join(ALLOWED_ATTACHMENT_EXTENSIONS)}"
            )
        if value.size > MAX_ATTACHMENT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"File size ({value.size / (1024*1024):.1f}MB) exceeds maximum limit of 3MB."
            )
        
        # Virus scan
        try:
            scan_file_for_malware(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

        return value


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_display = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "body",
            "is_internal_note",
            "is_system_note",
            "sent_by",
            "sender_name",
            "sender_display",
            "created_at",
        ]
        read_only_fields = ["id", "sender_display", "created_at"]

    def get_sender_display(self, obj):
        if obj.is_system_note:
            return "System"
        if obj.sent_by:
            if hasattr(obj.sent_by, "admin_profile") and obj.sent_by.admin_profile.full_name:
                return obj.sent_by.admin_profile.full_name
            return obj.sent_by.email
        return obj.sender_name or "Customer"


class TicketActivityLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TicketActivityLog
        fields = [
            "id",
            "ticket",
            "action_summary",
            "performed_by",
            "performed_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "performed_by_name", "created_at"]

    def get_performed_by_name(self, obj):
        if not obj.performed_by:
            return "System"
        if hasattr(obj.performed_by, "admin_profile") and obj.performed_by.admin_profile.full_name:
            return obj.performed_by.admin_profile.full_name
        return obj.performed_by.email


class RelatedTicketSerializer(serializers.ModelSerializer):
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "subject",
            "priority",
            "priority_display",
            "status",
            "status_display",
            "created_at",
        ]


class SupportTicketListSerializer(serializers.ModelSerializer):
    customer_display_name = serializers.SerializerMethodField()
    category_abbrev = serializers.SerializerMethodField()
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "priority",
            "priority_display",
            "status",
            "status_display",
            "customer_name",
            "customer_display_name",
            "customer_email",
            "main_category",
            "category_abbrev",
            "subject",
            "assigned_to",
            "assigned_to_name",
            "is_live",
            "archived_at",
            "created_at",
            "submitted_at",
        ]

    def get_customer_display_name(self, obj):
        return format_customer_display_name(obj.customer_name)

    def get_category_abbrev(self, obj):
        return get_category_abbreviation(obj.main_category)

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            if hasattr(obj.assigned_to, "admin_profile") and obj.assigned_to.admin_profile.full_name:
                return obj.assigned_to.admin_profile.full_name
            return obj.assigned_to.email
        return obj.assigned_name or "-"


class CustomerAccountDetailSerializer(serializers.Serializer):
    matched = serializers.BooleanField()
    user_id = serializers.IntegerField(allow_null=True)
    email = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField()
    plan_type = serializers.CharField(allow_null=True)


class SupportTicketDetailSerializer(serializers.ModelSerializer):
    customer_display_name = serializers.SerializerMethodField()
    category_abbrev = serializers.SerializerMethodField()
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    customer_account_info = serializers.SerializerMethodField()
    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    messages = TicketMessageSerializer(many=True, read_only=True)
    activity_logs = TicketActivityLogSerializer(many=True, read_only=True)
    related_tickets = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "source",
            "source_display",
            "form_id",
            "form_submission_id",
            "submitted_at",
            "customer_name",
            "customer_display_name",
            "customer_email",
            "customer_phone",
            "company_name",
            "account_email",
            "customer_user",
            "plan_type",
            "main_category",
            "subcategory",
            "category_abbrev",
            "subject",
            "description",
            "safety_critical",
            "platform",
            "device",
            "app_version",
            "preferred_contact_method",
            "assigned_to",
            "assigned_to_name",
            "assigned_name",
            "send_confirmation_email",
            "archived_at",
            "resolved_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "is_live",
            "customer_account_info",
            "attachments",
            "messages",
            "activity_logs",
            "related_tickets",
        ]

    def get_customer_display_name(self, obj):
        return format_customer_display_name(obj.customer_name)

    def get_category_abbrev(self, obj):
        return get_category_abbreviation(obj.main_category)

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            if hasattr(obj.assigned_to, "admin_profile") and obj.assigned_to.admin_profile.full_name:
                return obj.assigned_to.admin_profile.full_name
            return obj.assigned_to.email
        return obj.assigned_name or "-"

    def get_customer_account_info(self, obj):
        target_email = obj.account_email or obj.customer_email
        user_obj, plan_name, is_active = match_customer_account(target_email)
        full_name = None
        if user_obj and hasattr(user_obj, "admin_profile"):
            full_name = user_obj.admin_profile.full_name

        return {
            "matched": user_obj is not None,
            "user_id": user_obj.id if user_obj else None,
            "email": user_obj.email if user_obj else target_email,
            "full_name": full_name or obj.customer_name,
            "is_active": is_active,
            "plan_type": plan_name if user_obj else (obj.plan_type or "Not Found"),
        }

    def get_related_tickets(self, obj):
        if not obj.id or not obj.main_category:
            return []
        
        # Search same category or subject words
        first_word = (obj.subject.split()[0] if obj.subject else "")
        qs = (
            SupportTicket.objects.filter(main_category=obj.main_category)
            .exclude(id=obj.id)
            .exclude(status__in=[TicketStatus.CLOSED, TicketStatus.DRAFT])
            .exclude(archived_at__isnull=False)
        )
        if first_word and len(first_word) > 2:
            qs = qs.filter(subject__icontains=first_word)
        return RelatedTicketSerializer(qs[:5], many=True).data


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating tickets from the Admin Dashboard or saving drafts.
    """
    is_draft = serializers.BooleanField(default=False, write_only=True)
    internal_notes = serializers.CharField(required=False, allow_blank=True, write_only=True)
    uploaded_files = serializers.ListField(
        child=serializers.FileField(), required=False, write_only=True
    )

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "is_draft",
            "customer_name",
            "customer_email",
            "customer_phone",
            "company_name",
            "account_email",
            "plan_type",
            "customer_user",
            "main_category",
            "subcategory",
            "priority",
            "preferred_contact_method",
            "source",
            "assigned_to",
            "assigned_name",
            "subject",
            "description",
            "safety_critical",
            "platform",
            "device",
            "app_version",
            "send_confirmation_email",
            "internal_notes",
            "uploaded_files",
            "created_at",
        ]
        read_only_fields = ["id", "ticket_number", "created_at"]

    def validate_uploaded_files(self, files):
        if len(files) > MAX_ATTACHMENTS_PER_TICKET:
            raise serializers.ValidationError(
                f"Maximum {MAX_ATTACHMENTS_PER_TICKET} files allowed per ticket."
            )
        for f in files:
            ext = os.path.splitext(f.name)[1].lstrip(".").lower()
            if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
                raise serializers.ValidationError(
                    f"File extension '.{ext}' not allowed. Allowed: {', '.join(ALLOWED_ATTACHMENT_EXTENSIONS)}"
                )
            if f.size > MAX_ATTACHMENT_SIZE_BYTES:
                raise serializers.ValidationError(
                    f"File {f.name} exceeds 3MB limit."
                )
            try:
                scan_file_for_malware(f)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        return files

    def create(self, validated_data):
        is_draft = validated_data.pop("is_draft", False)
        internal_notes = validated_data.pop("internal_notes", "")
        uploaded_files = validated_data.pop("uploaded_files", [])
        user = self.context.get("request").user if self.context.get("request") else None

        with transaction.atomic():
            ticket = SupportTicket(**validated_data)
            ticket.created_by = user
            ticket.updated_by = user

            # Auto match customer account if not set
            if not ticket.customer_user and ticket.customer_email:
                matched_user, plan_name, _ = match_customer_account(ticket.customer_email)
                if matched_user:
                    ticket.customer_user = matched_user
                if not ticket.plan_type and plan_name != "Not Found":
                    ticket.plan_type = plan_name

            if is_draft:
                ticket.status = TicketStatus.DRAFT
                ticket.ticket_number = None
            else:
                ticket.status = TicketStatus.NEW
                ticket.ticket_number = generate_ticket_number()
                # If priority not explicitly overridden to non-normal, calculate priority
                if not ticket.priority or ticket.priority == TicketPriority.NORMAL:
                    ticket.priority = determine_ticket_priority(
                        safety_critical=ticket.safety_critical,
                        main_category=ticket.main_category,
                        subcategory=ticket.subcategory,
                    )

            ticket.save()

            # Handle initial internal notes
            if internal_notes:
                TicketMessage.objects.create(
                    ticket=ticket,
                    body=internal_notes,
                    is_internal_note=True,
                    sent_by=user,
                    sender_name=getattr(getattr(user, "admin_profile", None), "full_name", None) or "Admin",
                )

            # Handle attachments
            for f in uploaded_files:
                TicketAttachment.objects.create(
                    ticket=ticket,
                    file=f,
                    original_filename=f.name,
                    file_size=f.size,
                    file_type=os.path.splitext(f.name)[1].lstrip(".").lower(),
                    uploaded_by=user,
                )

            # Log creation
            TicketActivityLog.objects.create(
                ticket=ticket,
                action_summary=f"Ticket {'draft saved' if is_draft else 'created'}",
                performed_by=user,
            )

        # Trigger emails for non-drafts outside atomic block
        if not is_draft:
            if ticket.send_confirmation_email:
                send_customer_confirmation_email(ticket)
            if ticket.assigned_to:
                send_assignment_email(ticket, ticket.assigned_to, ticket.assigned_name)

        return ticket


class SupportTicketUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating ticket fields and recording activity logs.
    """
    class Meta:
        model = SupportTicket
        fields = [
            "status",
            "priority",
            "main_category",
            "subcategory",
            "assigned_to",
            "assigned_name",
            "source",
            "safety_critical",
            "platform",
            "device",
            "app_version",
            "preferred_contact_method",
            "company_name",
            "account_email",
            "plan_type",
        ]

    def update(self, instance, validated_data):
        user = self.context.get("request").user if self.context.get("request") else None
        changes = []

        old_assigned = instance.assigned_to
        for field, new_val in validated_data.items():
            old_val = getattr(instance, field)
            if old_val != new_val:
                setattr(instance, field, new_val)
                changes.append(f"Changed {field} from '{old_val}' to '{new_val}'")

        if validated_data.get("status") == TicketStatus.RESOLVED and not instance.resolved_at:
            instance.resolved_at = timezone.now()

        instance.updated_by = user
        instance.save()

        if changes:
            summary = "; ".join(changes)
            TicketActivityLog.objects.create(
                ticket=instance,
                action_summary=summary[:500],
                performed_by=user,
            )

        # Send assignment email if new assignee
        if "assigned_to" in validated_data and instance.assigned_to and instance.assigned_to != old_assigned:
            send_assignment_email(instance, instance.assigned_to, instance.assigned_name)

        return instance


class WebsiteTicketCreateSerializer(serializers.Serializer):
    """
    Handles website WPForms submission payload.
    Supports standard field names and WPForms subtopic identifiers.
    """
    source = serializers.CharField(required=False, default="WEBSITE_FORM")
    form_id = serializers.CharField(required=False, allow_blank=True, default="1278")
    form_submission_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    submitted_at = serializers.DateTimeField(required=False, default=timezone.now)

    customer_name = serializers.CharField(required=True)
    customer_email = serializers.EmailField(required=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    account_email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    plan_type = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    main_category = serializers.CharField(required=True)
    subcategory = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Subtopic fields from WPForms
    account_login_subtopic = serializers.CharField(required=False, allow_blank=True)
    billing_subscription_subtopic = serializers.CharField(required=False, allow_blank=True)
    permit_processing_subtopic = serializers.CharField(required=False, allow_blank=True)
    route_navigation_subtopic = serializers.CharField(required=False, allow_blank=True)
    app_technical_subtopic = serializers.CharField(required=False, allow_blank=True)
    app_tachnical_subtopic = serializers.CharField(required=False, allow_blank=True)  # typo in pdf
    team_driver_subtopic = serializers.CharField(required=False, allow_blank=True)
    acct_changes_requests_subtopic = serializers.CharField(required=False, allow_blank=True)
    complaint_serv_concern_subtopic = serializers.CharField(required=False, allow_blank=True)
    feature_suggestion_subtopic = serializers.CharField(required=False, allow_blank=True)
    general_question_other_subtopic = serializers.CharField(required=False, allow_blank=True)

    subject = serializers.CharField(required=True)
    description = serializers.CharField(required=True)
    safety_critical = serializers.BooleanField(required=False, default=False)
    platform = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    device = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    device_model = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    app_version = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    preferred_contact_method = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    perferred_contact_method = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def create(self, validated_data):
        form_submission_id = validated_data.get("form_submission_id")
        source = TicketSource.WEBSITE_FORM

        # 1. Duplicate check
        if form_submission_id:
            existing = SupportTicket.objects.filter(
                source=source, form_submission_id=form_submission_id
            ).first()
            if existing:
                return existing

        # 2. Extract and resolve category & subcategory
        raw_cat = validated_data.get("main_category", "")
        main_category = CATEGORY_LABEL_TO_KEY.get(raw_cat, raw_cat)
        if main_category not in MainCategory.values:
            main_category = MainCategory.GENERAL_OTHER

        # Resolve subcategory from individual subtopic fields if present
        subcategory = (
            validated_data.get("subcategory")
            or validated_data.get("account_login_subtopic")
            or validated_data.get("billing_subscription_subtopic")
            or validated_data.get("permit_processing_subtopic")
            or validated_data.get("route_navigation_subtopic")
            or validated_data.get("app_technical_subtopic")
            or validated_data.get("app_tachnical_subtopic")
            or validated_data.get("team_driver_subtopic")
            or validated_data.get("acct_changes_requests_subtopic")
            or validated_data.get("complaint_serv_concern_subtopic")
            or validated_data.get("feature_suggestion_subtopic")
            or validated_data.get("general_question_other_subtopic")
            or ""
        )

        customer_email = validated_data.get("customer_email")
        matched_user, matched_plan, _ = match_customer_account(customer_email)

        safety_critical = validated_data.get("safety_critical", False)
        priority = determine_ticket_priority(
            safety_critical=safety_critical,
            main_category=main_category,
            subcategory=subcategory,
        )

        contact_method = (
            validated_data.get("preferred_contact_method")
            or validated_data.get("perferred_contact_method")
            or ContactMethod.EMAIL
        )
        if contact_method.upper() in ContactMethod.values:
            contact_method = contact_method.upper()
        else:
            contact_method = ContactMethod.EMAIL

        device = validated_data.get("device") or validated_data.get("device_model")

        with transaction.atomic():
            ticket = SupportTicket.objects.create(
                ticket_number=generate_ticket_number(),
                status=TicketStatus.NEW,
                priority=priority,
                source=source,
                form_id=validated_data.get("form_id", "1278"),
                form_submission_id=form_submission_id,
                submitted_at=validated_data.get("submitted_at") or timezone.now(),
                customer_name=validated_data.get("customer_name"),
                customer_email=customer_email,
                customer_phone=validated_data.get("customer_phone"),
                company_name=validated_data.get("company_name"),
                account_email=validated_data.get("account_email") or customer_email,
                customer_user=matched_user,
                plan_type=validated_data.get("plan_type") or (matched_plan if matched_plan != "Not Found" else "Individual"),
                main_category=main_category,
                subcategory=subcategory,
                subject=validated_data.get("subject"),
                description=validated_data.get("description"),
                safety_critical=safety_critical,
                platform=validated_data.get("platform"),
                device=device,
                app_version=validated_data.get("app_version"),
                preferred_contact_method=contact_method,
                send_confirmation_email=True,
            )

            # Record activity log
            TicketActivityLog.objects.create(
                ticket=ticket,
                action_summary=f"Ticket submitted via Website Form (ID: {form_submission_id or 'N/A'})",
            )

        # Trigger emails
        send_customer_confirmation_email(ticket)
        send_staff_notification_email(ticket)

        return ticket


class TicketStatsSerializer(serializers.Serializer):
    live_tickets_count = serializers.IntegerField()
    archived_tickets_count = serializers.IntegerField()


class AssigneeOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField()


class CustomerSearchResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField(allow_blank=True, allow_null=True)
    phone = serializers.CharField(allow_blank=True, allow_null=True)
    company_name = serializers.CharField(allow_blank=True, allow_null=True)
    plan_type = serializers.CharField()
    is_active = serializers.BooleanField()
