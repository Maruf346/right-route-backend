import uuid
import random
import secrets
from django.db import models
from django.utils import timezone

from core.common_models import BaseModel
from security.constants import DataRequestStatus, RequestType, RequestSource


def generate_request_id():
    """Generate a unique DR-YYYY-XXXX request ID. The 4-digit suffix is
    random and guaranteed to not already exist in the database."""
    year = timezone.now().year
    for _ in range(1000):  # safety cap on retries
        suffix = str(random.randint(0, 9999)).zfill(4)
        candidate = f"DR-{year}-{suffix}"
        if not DataProtectionRequest.objects.filter(request_id=candidate).exists():
            return candidate
    # Extremely unlikely fallback: use a random uuid hex fragment
    return f"DR-{year}-{secrets.token_hex(2).upper()}"


def generate_download_token():
    """Generate a cryptographically secure, unique download token."""
    for _ in range(100):
        token = secrets.token_urlsafe(32)
        if not DataProtectionRequest.objects.filter(export_download_token=token).exists():
            return token
    return secrets.token_urlsafe(48)


class DataProtectionRequest(BaseModel):
    """
    Represents a single GDPR / data-protection request submitted by a customer
    and processed by an admin through the dashboard.

    Status flow:  NEW  →  PENDING_APPROVAL  →  COMPLETED
    """

    # ── Core identifiers ───────────────────────────────────────────────────────
    request_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Auto-generated DR-YYYY-XXXX identifier.",
    )
    date_requested = models.DateTimeField(
        help_text="When RightRoute received the request (defaults to now, admin-correctable).",
    )

    # ── Customer info (auto-filled after FIND) ─────────────────────────────────
    customer_email = models.EmailField(
        help_text="Email provided by the customer at time of request.",
    )
    customer_user = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_protection_requests",
        help_text="Linked RightRoute account (resolved via FIND button).",
    )
    customer_name = models.CharField(max_length=255, blank=True, default="")
    plan_type = models.CharField(max_length=50, blank=True, default="")
    account_status = models.CharField(max_length=50, blank=True, default="")
    account_created_at = models.DateTimeField(null=True, blank=True)
    phone_number = models.CharField(max_length=50, blank=True, default="")

    # ── Request details ─────────────────────────────────────────────────────────
    source = models.CharField(
        max_length=20,
        choices=RequestSource.choices,
        blank=True,
        default="",
    )
    source_other_detail = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Required when source=OTHER.",
    )
    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
        blank=True,
        default="",
    )

    # ── Status ──────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=DataRequestStatus.choices,
        default=DataRequestStatus.NEW,
        db_index=True,
    )

    # ── Approval fields (checkboxes + text on the form) ────────────────────────
    approval_received = models.BooleanField(
        default=False,
        help_text="Customer replied confirming the requested action.",
    )
    approval_source = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="How the approval arrived (email, phone, letter, etc.).",
    )
    approval_received_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date admin received the customer's approval.",
    )
    admin_confirmed = models.BooleanField(
        default=False,
        help_text=(
            "Admin has confirmed: approval came from a verified email; "
            "the action is correct; and, for deletion/anonymization, the action may be irreversible."
        ),
    )

    # ── Approval email tracking ─────────────────────────────────────────────────
    approval_email_sent_at = models.DateTimeField(null=True, blank=True)
    approval_email_sent_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_approval_emails",
    )

    # ── Execution tracking ──────────────────────────────────────────────────────
    performed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the backend process was triggered.",
    )
    performed_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_data_requests",
    )
    perform_result = models.TextField(
        blank=True,
        default="",
        help_text="System-generated summary of what was done during perform.",
    )

    # ── Completion ──────────────────────────────────────────────────────────────
    completed_at = models.DateTimeField(null=True, blank=True)

    # ── Export-specific fields ──────────────────────────────────────────────────
    export_zip_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Relative path to the generated ZIP file in protected storage.",
    )
    export_zip_size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes.",
    )
    export_zip_created_at = models.DateTimeField(null=True, blank=True)
    export_zip_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Download link expires after 7 days.",
    )
    export_download_token = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Secure token used in the download URL; revocable by RightRoute.",
    )

    # ── Audit fields ────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_data_requests",
    )
    updated_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_data_requests",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Data Protection Request"
        verbose_name_plural = "Data Protection Requests"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["customer_email"]),
            models.Index(fields=["request_id"]),
        ]

    def save(self, *args, **kwargs):
        # Auto-set date_requested on first save if not provided
        if not self.date_requested:
            self.date_requested = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.request_id} — {self.customer_email} ({self.status})"

    # ── Computed warning flags ──────────────────────────────────────────────────

    def get_warnings(self):
        """
        Returns a list of warning strings for the admin UI. These never block the
        request — they only alert the admin to issues requiring attention before
        processing.
        """
        if not self.customer_user:
            return []

        warnings = []
        user = self.customer_user

        # 1. Active paid subscription
        has_active_subscription = user.subscriptions.filter(
            status="ACTIVE"
        ).exists() if hasattr(user, "subscriptions") else False
        if has_active_subscription:
            warnings.append(
                "Active paid subscription: The user may be asking for a data deletion for an "
                "active open account."
            )

        # 2. Open billing dispute
        # TODO: Integrate with billing dispute model when available.

        # 3. Previous privacy request already open
        open_request_exists = (
            DataProtectionRequest.objects
            .filter(customer_user=user)
            .exclude(status=DataRequestStatus.COMPLETED)
            .exclude(pk=self.pk)
            .exists()
        )
        if open_request_exists:
            warnings.append(
                "Previous privacy request already open: The customer has previously submitted "
                "a data request that has not been completed."
            )

        # 4. Customer account blocked
        from core.constants import UserStatus
        if user.status == UserStatus.BLOCKED:
            warnings.append(
                "Customer account blocked: The customer's account is currently blocked."
            )

        return warnings

    @property
    def can_save_as_pending(self):
        """All conditions for SAVE AS PENDING APPROVAL to be active."""
        return bool(
            self.customer_user
            and self.request_type
            and self.approval_email_sent_at
            and self.customer_email
        )

    @property
    def can_perform(self):
        """All four checks must be complete before PERFORM APPROVED REQUEST activates."""
        return bool(
            self.approval_received
            and self.approval_source
            and self.approval_received_date
            and self.admin_confirmed
        )

    @property
    def can_send_completion_email(self):
        """SEND COMPLETION EMAIL AND CLOSE is active only after perform succeeds."""
        if self.request_type == RequestType.EXPORT:
            return bool(self.performed_at and self.export_zip_path and self.export_download_token)
        return bool(self.performed_at)


class DataRequestNote(models.Model):
    """
    Append-only notes and correspondence for a DataProtectionRequest.
    Notes are shown in descending order (newest at top).
    System-generated notes (is_system_note=True) are created by the backend.
    """

    request = models.ForeignKey(
        DataProtectionRequest,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    body = models.TextField()
    written_by = models.ForeignKey(
        "account.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_request_notes",
        help_text="Null for system-generated notes.",
    )
    is_system_note = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Data Request Note"
        verbose_name_plural = "Data Request Notes"

    def __str__(self):
        author = self.written_by.email if self.written_by else "System"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {author}: {self.body[:60]}"
