import os
from django.db import models
from django.utils import timezone
from datetime import timedelta

from core.common_models import BaseModel
from account.models import User
from supports.constants import (
    ContactMethod,
    MainCategory,
    PlanType,
    TicketPriority,
    TicketSource,
    TicketStatus,
)


class SupportTicket(BaseModel):
    """
    Main model representing a support ticket submitted either via the website
    support form (WPForms) or created directly by an admin in the dashboard.
    """
    ticket_number = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Format: RR-YYYY-00001",
    )
    status = models.CharField(
        max_length=30,
        choices=TicketStatus.choices,
        default=TicketStatus.NEW,
        db_index=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
        db_index=True,
    )
    source = models.CharField(
        max_length=40,
        choices=TicketSource.choices,
        default=TicketSource.WEBSITE_FORM,
        db_index=True,
    )

    # ── External Form Identifiers (Duplicate prevention) ──────────────────────
    form_id = models.CharField(max_length=50, blank=True, null=True)
    form_submission_id = models.CharField(max_length=100, blank=True, null=True)
    submitted_at = models.DateTimeField(default=timezone.now)

    # ── Customer & Account Information ─────────────────────────────────────────
    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField(max_length=255, db_index=True)
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    account_email = models.EmailField(max_length=255, blank=True, null=True)
    customer_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    plan_type = models.CharField(max_length=50, blank=True, null=True)

    # ── Classification & Content ───────────────────────────────────────────────
    main_category = models.CharField(
        max_length=50,
        choices=MainCategory.choices,
        db_index=True,
    )
    subcategory = models.CharField(max_length=255, blank=True, null=True)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    safety_critical = models.BooleanField(default=False)

    # ── Technical & Device details ────────────────────────────────────────────
    platform = models.CharField(max_length=50, blank=True, null=True)  # Android / iOS
    device = models.CharField(max_length=100, blank=True, null=True)
    app_version = models.CharField(max_length=50, blank=True, null=True)
    preferred_contact_method = models.CharField(
        max_length=30,
        choices=ContactMethod.choices,
        default=ContactMethod.EMAIL,
        blank=True,
        null=True,
    )

    # ── Assignment & Workflow ─────────────────────────────────────────────────
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_tickets",
    )
    assigned_name = models.CharField(max_length=255, blank=True, null=True)
    send_confirmation_email = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_support_tickets",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_support_tickets",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "form_submission_id"],
                condition=models.Q(form_submission_id__isnull=False) & ~models.Q(form_submission_id=""),
                name="unique_support_ticket_submission",
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["main_category"]),
            models.Index(fields=["customer_email"]),
            models.Index(fields=["archived_at"]),
        ]

    def __str__(self):
        return f"{self.ticket_number or 'Draft'} - {self.subject}"

    @property
    def is_live(self):
        return self.archived_at is None and self.status not in [TicketStatus.CLOSED, TicketStatus.DRAFT]

    def refresh_auto_status(self):
        """
        If ticket is NEW and was created more than 3 hours ago, auto-transition to OPEN.
        """
        if self.status == TicketStatus.NEW and not self.archived_at:
            time_threshold = timezone.now() - timedelta(hours=3)
            if self.created_at and self.created_at <= time_threshold:
                self.status = TicketStatus.OPEN
                self.save(update_fields=["status", "updated_at"])


class TicketAttachment(BaseModel):
    """
    Attachments uploaded with a ticket or in subsequent message threads.
    Max 3 per ticket, 3MB each, limited extensions.
    """
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="support_attachments/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)  # in bytes
    file_type = models.CharField(max_length=50, blank=True, null=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_ticket_attachments",
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.ticket.ticket_number or 'Draft'})"

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = os.path.basename(self.file.name)
        if self.file and not self.file_size:
            try:
                self.file_size = self.file.size
            except Exception:
                pass
        if self.original_filename and not self.file_type:
            self.file_type = self.original_filename.split(".")[-1].lower()
        super().save(*args, **kwargs)


class TicketMessage(BaseModel):
    """
    Represents a conversation item in the ticket thread:
    - Customer responses
    - Admin/Agent replies sent to customer
    - Internal notes (only visible to staff)
    - System notes (automated logs)
    """
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    body = models.TextField()
    is_internal_note = models.BooleanField(
        default=False,
        help_text="If True, this is an internal note never sent to customer.",
    )
    is_system_note = models.BooleanField(
        default=False,
        help_text="If True, this message was auto-generated by the backend.",
    )
    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_ticket_messages",
    )
    sender_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        msg_type = "Internal Note" if self.is_internal_note else ("System" if self.is_system_note else "Message")
        return f"[{msg_type}] {self.ticket.ticket_number or 'Draft'}: {self.body[:40]}"


class TicketActivityLog(BaseModel):
    """
    Session activity log summarizing updates made to the ticket.
    """
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    action_summary = models.CharField(max_length=500)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_activities",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number}: {self.action_summary}"
