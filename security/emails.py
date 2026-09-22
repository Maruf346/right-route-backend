"""
Email helpers for the Security / Data Protection app.

All emails are sent to the verified account email on the request.
Admins cannot change the recipient.
"""

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from core.models import EmailConfig
from security.constants import RequestType


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _get_logo_url():
    """Return absolute URL for the RightRoute logo used in emails."""
    site_url = getattr(settings, "SITE_URL", "https://getrightroute.app")
    return f"{site_url}/static/logo.png"


def _email_header(logo_url):
    """Returns the HTML header block with the RightRoute logo."""
    return f"""
    <table width="600" cellpadding="0" cellspacing="0" style="margin:0 auto;background:#ffffff;border:1px solid #e0e0e0;border-radius:4px;overflow:hidden;">
        <tr><td align="center" style="padding:32px 40px 24px;">
            <img src="{logo_url}" alt="RightRoute" width="200" style="display:block;max-width:200px;height:auto;border:0;">
        </td></tr>
        <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e0e0e0;margin:0;"></td></tr>
        <tr><td style="padding:32px 40px;font-family:Arial,sans-serif;color:#222222;font-size:16px;line-height:1.6;">
    """


def _email_footer():
    """Returns the HTML footer block with RightRoute branding."""
    return """
        </td></tr>
        <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e0e0e0;margin:0;"></td></tr>
        <tr><td style="padding:24px 40px;font-family:Arial,sans-serif;">
            <p style="margin:0;font-size:14px;color:#444444;line-height:1.8;">
                RightRoute&trade;<br>
                &copy; 2026 Leavitt &amp; Davis LLC. All Rights Reserved.<br>
                1-888-603-6317<br>
                getrightroute.app<br>
                This is an automated email. Please do not reply.
            </p>
        </td></tr>
    </table>
    """


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

    logo_url = _get_logo_url()
    body = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:20px 0;background:#f5f5f5;'>"
        + _email_header(logo_url)
        + f"""
        <p>Dear {request_obj.customer_name or request_obj.customer_email},</p>
        {personal_section}
        <p>We have received a data request on your behalf. Below are the details of your request.
        Please review carefully and reply to approve or reject this action.</p>

        <h3 style="margin:20px 0 8px;">Request Summary</h3>
        <table style="border-collapse:collapse;width:100%;font-size:15px;">
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Request ID</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.request_id}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Date Requested</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Account Email</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.customer_email}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Customer Name</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.customer_name or "N/A"}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Plan Type</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.plan_type or "N/A"}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Account Status</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.account_status or "N/A"}</td>
            </tr>
        </table>

        <h3 style="margin:20px 0 8px;">Request Type: {request_obj.get_request_type_display()}</h3>
        <p>{description}</p>

        <h3 style="margin:20px 0 8px;">Data Categories Affected</h3>
        <p><em>
            For this request type, all eligible personal data associated with your RightRoute
            account will be processed as described above.
        </em></p>

        {irreversibility_warning}

        <h3 style="margin:20px 0 8px;">How to Approve This Request</h3>
        <p>Please reply to this email with your explicit confirmation that you authorise
        RightRoute to perform the action described above. Include in your reply:</p>
        <ul>
            <li>Your full name</li>
            <li>Your account email address</li>
            <li>The phrase: <strong>"I approve Request {request_obj.request_id}"</strong></li>
        </ul>

        <p><strong>Important:</strong> RightRoute will not take any action until we receive
        your written approval. If you did not submit this request, please contact us immediately.</p>

        <p style="margin-top:24px;">Kind regards,<br>
        <strong>RightRoute Support Team</strong></p>
        """
        + _email_footer()
        + "</body></html>"
    )
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

    logo_url = _get_logo_url()
    body = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:20px 0;background:#f5f5f5;'>"
        + _email_header(logo_url)
        + f"""
        <p>Dear {request_obj.customer_name or request_obj.customer_email},</p>
        <p>Your data protection request <strong>{request_obj.request_id}</strong> has been
        completed. Below is a full summary.</p>

        <h3 style="margin:20px 0 8px;">Request Details</h3>
        <table style="border-collapse:collapse;width:100%;font-size:15px;">
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Request ID</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.request_id}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Request Type</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.get_request_type_display()}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Date Requested</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</td>
            </tr>
            <tr>
                <td style="padding:6px;border:1px solid #ddd;font-weight:bold;">Completed On</td>
                <td style="padding:6px;border:1px solid #ddd;">{request_obj.completed_at.strftime("%d %B %Y, %H:%M UTC") if request_obj.completed_at else "N/A"}</td>
            </tr>
        </table>

        {download_section}

        <h3 style="margin:20px 0 8px;">Correspondence &amp; Notes</h3>
        {notes_html or "<p><em>No notes recorded.</em></p>"}

        <p style="margin-top:24px;">If you have questions, please contact our support team.</p>
        <p>Kind regards,<br>
        <strong>RightRoute Support Team</strong></p>
        """
        + _email_footer()
        + "</body></html>"
    )
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


# ── Team Dashboard Request Emails ─────────────────────────────────────────────

def send_team_request_received_email(request_obj):
    """
    Sends confirmation email to customer that RightRoute received their Data Protection request.
    """
    try:
        conn, config = _get_connection()
    except Exception:
        return ""

    logo_url = _get_logo_url()
    body = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:20px 0;background:#f5f5f5;'>"
        + _email_header(logo_url)
        + f"""
        <p>Dear {request_obj.customer_name or request_obj.customer_email},</p>
        <p>We have received your data protection request (ID: <strong>{request_obj.request_id}</strong>).</p>
        <p><strong>Request Type:</strong> {request_obj.get_request_type_display()}</p>
        <p><strong>Date Requested:</strong> {request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</p>
        <p>Our security and compliance team will review your request and contact you soon to verify and process it.</p>
        <p style="margin-top:24px;">Kind regards,<br>
        <strong>RightRoute Security &amp; Compliance Team</strong></p>
        """
        + _email_footer()
        + "</body></html>"
    )
    subject = f"RightRoute Data Protection Request Received ({request_obj.request_id})"
    try:
        _send(subject, body, request_obj.customer_email, config, conn)
    except Exception:
        pass
    return body


def send_team_request_staff_alert(request_obj):
    """
    Sends alert email to help@getrightroute.app when a team submits a data protection request.
    """
    try:
        conn, config = _get_connection()
    except Exception:
        return ""

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2>[Security Alert] New Data Protection Request Submitted</h2>
        <p>A new data protection request has been submitted from the Team Dashboard.</p>
        <table style="border-collapse: collapse; width: 100%;">
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Request ID</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.request_id}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Customer Name</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.customer_name}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Account Email</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.customer_email}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Phone</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.phone_number or 'N/A'}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Plan Type</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.plan_type}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Request Type</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.get_request_type_display()}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Date</td><td style="padding: 6px; border: 1px solid #ddd;">{request_obj.date_requested.strftime("%d %B %Y, %H:%M UTC")}</td></tr>
        </table>
        <br>
        <p>Please review and process this request in the Admin Dashboard > Security > Data Protection page.</p>
    </body>
    </html>
    """
    subject = f"[New Data Request] {request_obj.request_id} - {request_obj.customer_name or request_obj.customer_email}"
    try:
        _send(subject, body, "help@getrightroute.app", config, conn)
    except Exception:
        pass
    return body

