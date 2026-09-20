"""
Email helpers for the Security / Data Protection app.

All emails are sent to the verified account email on the request.
Admins cannot change the recipient.
"""

from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from core.models import EmailConfig
from security.constants import RequestType


# ── Shared builder ─────────────────────────────────────────────────────────────

def _get_connection():
    """Return a Django mail connection from the active EmailConfig."""
    config = EmailConfig.objects.filter(is_active=True).first()
    if not config:
        raise RuntimeError("No active email configuration found.")
    conn = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=config.host,
        port=int(config.port),
        username=config.host_user,
        password=config.host_password,
        use_tls=config.tls,
        fail_silently=False,
    )
    return conn, config


def _send(subject, body_html, to_email, config, conn):
    """Low-level send with HTML body."""
    msg = EmailMessage(
        subject=subject,
        body=body_html,
        from_email=f"{config.name} <{config.email}>",
        to=[to_email],
        connection=conn,
    )
    msg.content_subtype = "html"
    msg.send()


# ── Approval email ─────────────────────────────────────────────────────────────

def build_approval_email_body(request_obj, personal_message=""):
    """
    Formats the approval email content per the PDF specification.
    Includes: request ID, customer account info, selected request type,
    plain-language explanation, data categories affected, irreversibility warning,
    approval instructions, and a statement that RightRoute will not act without approval.
    """
    from security.constants import REQUEST_TYPE_DESCRIPTIONS

    description = REQUEST_TYPE_DESCRIPTIONS.get(request_obj.request_type, "")
    is_destructive = request_obj.request_type in (RequestType.DELETE, RequestType.DELETE_ANONYMIZE)

    irreversibility_warning = ""
    if is_destructive:
        irreversibility_warning = (
            "<p><strong>⚠️ Warning:</strong> This action may be irreversible. "
            "Once performed, deleted or anonymized data cannot be recovered.</p>"
        )

    personal_section = ""
    if personal_message:
        personal_section = f"<p><em>{personal_message}</em></p><hr>"

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2>RightRoute — Data Protection Request</h2>
        <p>Dear {request_obj.customer_name or request_obj.customer_email},</p>
        {personal_section}
        <p>We have received a data request on your behalf. Below are the details of your request.
        Please review carefully and reply to approve or reject this action.</p>

        <h3>Request Summary</h3>
        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Request ID</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.request_id}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Date Requested</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Account Email</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.customer_email}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Customer Name</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.customer_name or "N/A"}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Plan Type</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.plan_type or "N/A"}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Account Status</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.account_status or "N/A"}</td>
            </tr>
        </table>

        <h3>Request Type: {request_obj.get_request_type_display()}</h3>
        <p>{description}</p>

        <h3>Data Categories Affected</h3>
        <p><em>
            <!-- TODO: Insert specific data categories for this request type once the retention
                 category list is provided. For Export: all profile, route, permit, and billing
                 data associated with the account will be included. -->
            For this request type, all eligible personal data associated with your RightRoute
            account will be processed as described above.
        </em></p>

        {irreversibility_warning}

        <h3>How to Approve This Request</h3>
        <p>Please reply to this email with your explicit confirmation that you authorise
        RightRoute to perform the action described above. Include in your reply:</p>
        <ul>
            <li>Your full name</li>
            <li>Your account email address</li>
            <li>The phrase: <strong>"I approve Request {request_obj.request_id}"</strong></li>
        </ul>

        <p><strong>Important:</strong> RightRoute will not take any action until we receive
        your written approval. If you did not submit this request, please contact us immediately.</p>

        <br>
        <p>Kind regards,<br>
        <strong>RightRoute Support Team</strong></p>
    </body>
    </html>
    """
    return body.strip()


def send_approval_email(request_obj, personal_message=""):
    """
    Sends the approval email to the verified account email.
    Returns the formatted email body (for logging to Notes).
    Raises RuntimeError if no active email config is found.
    """
    conn, config = _get_connection()
    body = build_approval_email_body(request_obj, personal_message)
    subject = f"RightRoute Data Request — Action Required ({request_obj.request_id})"
    _send(subject, body, request_obj.customer_email, config, conn)
    return body


# ── Completion email ────────────────────────────────────────────────────────────

def build_completion_email_body(request_obj):
    """
    Formats the completion email. For EXPORT requests includes the secure download
    link with a 7-day expiry warning. For all types includes full form contents and notes.
    """
    from django.conf import settings

    notes_html = ""
    for note in request_obj.notes.order_by("-created_at"):
        author = note.written_by.email if note.written_by else "System"
        notes_html += (
            f"<p style='border-left: 3px solid #ddd; padding-left: 10px; margin: 8px 0;'>"
            f"<strong>[{note.created_at.strftime('%d %b %Y %H:%M UTC')}] {author}:</strong><br>"
            f"{note.body}</p>"
        )

    download_section = ""
    if request_obj.request_type == RequestType.EXPORT and request_obj.export_download_token:
        base_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
        download_url = f"{base_url}/api/v1/security/data-protection/download/{request_obj.export_download_token}/"
        expires_str = (
            request_obj.export_zip_expires_at.strftime("%d %B %Y, %H:%M UTC")
            if request_obj.export_zip_expires_at else "7 days from generation"
        )
        download_section = f"""
        <h3>Your Data Export</h3>
        <p>Your data export package is ready for download:</p>
        <p><a href="{download_url}" style="background: #1a56db; color: white; padding: 10px 20px;
            text-decoration: none; border-radius: 4px;">Download Your Data (ZIP)</a></p>
        <p><strong>⚠️ This link expires on {expires_str}.</strong>
        It is not publicly accessible and can only be used once from your device.</p>
        """

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2>RightRoute — Data Request Completed</h2>
        <p>Dear {request_obj.customer_name or request_obj.customer_email},</p>
        <p>Your data protection request <strong>{request_obj.request_id}</strong> has been
        completed. Below is a full summary.</p>

        <h3>Request Details</h3>
        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Request ID</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.request_id}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Request Type</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.get_request_type_display()}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Date Requested</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</td>
            </tr>
            <tr>
                <td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Completed On</td>
                <td style="padding: 6px; border: 1px solid #ddd;">{request_obj.completed_at.strftime("%d %B %Y, %H:%M UTC") if request_obj.completed_at else "N/A"}</td>
            </tr>
        </table>

        {download_section}

        <h3>Correspondence &amp; Notes</h3>
        {notes_html or "<p><em>No notes recorded.</em></p>"}

        <br>
        <p>If you have questions, please contact our support team.</p>
        <p>Kind regards,<br>
        <strong>RightRoute Support Team</strong></p>
    </body>
    </html>
    """
    return body.strip()


def send_completion_email(request_obj):
    """
    Sends the completion email to the verified account email.
    Returns the formatted email body (for logging to Notes).
    """
    conn, config = _get_connection()
    body = build_completion_email_body(request_obj)
    subject = f"RightRoute Data Request Completed ({request_obj.request_id})"
    _send(subject, body, request_obj.customer_email, config, conn)
    return body
