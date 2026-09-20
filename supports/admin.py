from django.contrib import admin
from supports.models import (
    SupportTicket,
    TicketAttachment,
    TicketMessage,
    TicketActivityLog,
)


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ("original_filename", "file_size", "file_type", "uploaded_by", "created_at")


class TicketMessageInline(admin.StackedInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ("created_at",)


class TicketActivityLogInline(admin.TabularInline):
    model = TicketActivityLog
    extra = 0
    readonly_fields = ("action_summary", "performed_by", "created_at")


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_number",
        "customer_name",
        "customer_email",
        "main_category",
        "priority",
        "status",
        "assigned_to",
        "source",
        "created_at",
    )
    list_filter = ("status", "priority", "main_category", "source", "safety_critical")
    search_fields = ("ticket_number", "customer_name", "customer_email", "subject", "description")
    readonly_fields = ("ticket_number", "created_at", "updated_at", "submitted_at")
    inlines = [TicketAttachmentInline, TicketMessageInline, TicketActivityLogInline]


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "ticket", "file_size", "file_type", "uploaded_by", "created_at")
    search_fields = ("original_filename", "ticket__ticket_number")


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "sender_name", "is_internal_note", "is_system_note", "created_at")
    list_filter = ("is_internal_note", "is_system_note")
    search_fields = ("body", "ticket__ticket_number")


@admin.register(TicketActivityLog)
class TicketActivityLogAdmin(admin.ModelAdmin):
    list_display = ("ticket", "action_summary", "performed_by", "created_at")
    search_fields = ("action_summary", "ticket__ticket_number")
