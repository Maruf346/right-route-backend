from django.contrib import admin
from security.models import DataProtectionRequest, DataRequestNote


class DataRequestNoteInline(admin.TabularInline):
    model = DataRequestNote
    extra = 0
    readonly_fields = ("written_by", "is_system_note", "created_at")
    can_delete = False  # Notes are append-only

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DataProtectionRequest)
class DataProtectionRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_id",
        "customer_email",
        "customer_name",
        "request_type",
        "status",
        "date_requested",
        "created_at",
    )
    list_filter = ("status", "request_type", "source")
    search_fields = ("request_id", "customer_email", "customer_name")
    readonly_fields = (
        "request_id",
        "created_at",
        "updated_at",
        "approval_email_sent_at",
        "approval_email_sent_by",
        "performed_at",
        "performed_by",
        "completed_at",
        "export_download_token",
        "export_zip_created_at",
        "export_zip_expires_at",
        "export_zip_size",
        "perform_result",
    )
    inlines = [DataRequestNoteInline]

    fieldsets = (
        ("Identifiers", {
            "fields": ("request_id", "status", "date_requested"),
        }),
        ("Customer", {
            "fields": (
                "customer_email", "customer_user", "customer_name",
                "plan_type", "account_status", "account_created_at", "phone_number",
            ),
        }),
        ("Request Details", {
            "fields": ("source", "source_other_detail", "request_type"),
        }),
        ("Approval", {
            "fields": (
                "approval_received", "approval_source", "approval_received_date",
                "admin_confirmed", "approval_email_sent_at", "approval_email_sent_by",
            ),
        }),
        ("Execution", {
            "fields": ("performed_at", "performed_by", "perform_result", "completed_at"),
        }),
        ("Export", {
            "fields": (
                "export_zip_path", "export_zip_size",
                "export_zip_created_at", "export_zip_expires_at", "export_download_token",
            ),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields": ("created_by", "updated_by", "created_at", "updated_at"),
        }),
    )


@admin.register(DataRequestNote)
class DataRequestNoteAdmin(admin.ModelAdmin):
    list_display = ("request", "written_by", "is_system_note", "created_at")
    list_filter = ("is_system_note",)
    search_fields = ("request__request_id", "body")
    readonly_fields = ("created_at",)

    def has_change_permission(self, request, obj=None):
        return False  # Notes are immutable once saved
