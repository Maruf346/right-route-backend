"""
Email helpers for Support Tickets app.
Sends confirmation, staff alert, assignment, and response emails using the active EmailConfig.
"""

import logging
from django.core.mail import EmailMessage, get_connection
from django.conf import settings
from core.models import EmailConfig

logger = logging.getLogger(__name__)

STAFF_SUPPORT_EMAIL = "help@getrightroute.app"


def _get_connection():
    """Return a Django mail connection from the active EmailConfig."""
    config = EmailConfig.objects.filter(is_active=True).first()
    if not config:
        return None, None
    try:
        conn = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=config.host,
            port=int(config.port or 587),
            username=config.host_user,
            password=config.host_password,
            use_tls=config.tls,
            fail_silently=False,
        )
        return conn, config
    except Exception as e:
        logger.error(f"Failed to initialize email connection: {e}")
        return None, None


def _send_email(subject, body_html, to_emails):
    """Safely sends HTML email with fallback logging."""
    conn, config = _get_connection()
    if not conn or not config:
        logger.warning(f"Skipping email to {to_emails} - no active EmailConfig found.")
        return False

    from_sender = f"{config.name or 'RightRoute Support'} <{config.email}>"
    if isinstance(to_emails, str):
        to_emails = [to_emails]

    try:
        msg = EmailMessage(
            subject=subject,
            body=body_html,
            from_email=from_sender,
            to=to_emails,
            connection=conn,
        )
        msg.content_subtype = "html"
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error(f"Error sending support email to {to_emails}: {e}")
        return False


def send_customer_confirmation_email(ticket):
    """
    Sends receipt confirmation to customer with ticket number and submitted details.
    """
    if not ticket.customer_email or not ticket.send_confirmation_email:
        return False

    subject = f"RightRoute Support Ticket Created: {ticket.ticket_number or 'Pending'}"
    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #1a56db;">RightRoute Support Confirmation</h2>
        <p>Dear {ticket.customer_name},</p>
        <p>Thank you for contacting RightRoute Support. Your request has been received and logged into our system.</p>
        
        <table style="border-collapse: collapse; width: 100%; margin: 20px 0; max-width: 600px;">
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; width: 35%;">Ticket Number:</td><td style="padding: 8px; border: 1px solid #ddd;">{ticket.ticket_number}</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Subject:</td><td style="padding: 8px; border: 1px solid #ddd;">{ticket.subject}</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Category:</td><td style="padding: 8px; border: 1px solid #ddd;">{ticket.get_main_category_display()}</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Status:</td><td style="padding: 8px; border: 1px solid #ddd;">{ticket.get_status_display()}</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Description:</td><td style="padding: 8px; border: 1px solid #ddd;">{ticket.description}</td></tr>
        </table>

        <p>A member of our support team is reviewing your ticket and will respond as soon as possible.</p>
        <p>Best regards,<br><strong>RightRoute Support Team</strong></p>
    </div>
    """
    return _send_email(subject, body_html, ticket.customer_email)


def send_staff_notification_email(ticket):
    """
    Sends internal notification to help@getrightroute.app when a new ticket is submitted.
    """
    subject = f"New Support Ticket: {ticket.ticket_number} - {ticket.subject}"
    dashboard_url = f"https://admin.getrightroute.app/support/tickets/{ticket.id}"
    
    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h3 style="color: #1a56db;">New Ticket Submitted: {ticket.ticket_number}</h3>
        <p><strong>Priority:</strong> <span style="color: {'red' if ticket.priority in ['HIGH', 'URGENT'] else '#333'}; font-weight: bold;">{ticket.get_priority_display()}</span></p>
        
        <table style="border-collapse: collapse; width: 100%; margin: 15px 0; max-width: 600px;">
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold; width: 30%;">Ticket:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.ticket_number}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Customer:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.customer_name} ({ticket.customer_email})</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Phone:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.customer_phone or '-'}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Category:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.get_main_category_display()}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Subcategory:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.subcategory or '-'}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Subject:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.subject}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Description:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.description}</td></tr>
            <tr><td style="padding: 6px; border: 1px solid #ddd; font-weight: bold;">Submitted:</td><td style="padding: 6px; border: 1px solid #ddd;">{ticket.submitted_at}</td></tr>
        </table>

        <p><a href="{dashboard_url}" style="background-color: #1a56db; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; display: inline-block;">Open Ticket in Admin Dashboard</a></p>
    </div>
    """
    return _send_email(subject, body_html, STAFF_SUPPORT_EMAIL)


def send_assignment_email(ticket, assignee_user, assignee_name=None):
    """
    Sends notification to assigned technician.
    """
    target_email = None
    name = assignee_name or "Technician"

    if assignee_user:
        target_email = assignee_user.email
        if hasattr(assignee_user, "admin_profile") and assignee_user.admin_profile.full_name:
            name = assignee_user.admin_profile.full_name

    if not target_email:
        return False

    subject = f"Support ticket assigned: {ticket.ticket_number}"
    dashboard_url = f"https://admin.getrightroute.app/support/tickets/{ticket.id}"

    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Hello {name},</p>
        <p>Ticket number <strong>{ticket.ticket_number}</strong> has been assigned to you.</p>
        <p><strong>Subject:</strong> {ticket.subject}<br>
           <strong>Priority:</strong> {ticket.get_priority_display()}<br>
           <strong>Customer:</strong> {ticket.customer_name}</p>
        <p><a href="{dashboard_url}" style="background-color: #1a56db; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; display: inline-block;">View Ticket</a></p>
    </div>
    """
    return _send_email(subject, body_html, target_email)


def send_customer_response_email(ticket, response_text):
    """
    Sends message/response written in ticket thread to customer.
    """
    if not ticket.customer_email:
        return False

    subject = f"Update regarding Support Ticket: {ticket.ticket_number}"
    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Dear {ticket.customer_name},</p>
        <p>A message has been posted on your support ticket (<strong>{ticket.ticket_number}</strong>):</p>
        
        <div style="background-color: #f8f9fa; border-left: 4px solid #1a56db; padding: 12px 16px; margin: 15px 0;">
            {response_text}
        </div>

        <p>If you have any further questions, please reply to this email or visit our support page.</p>
        <p>Best regards,<br><strong>RightRoute Support Team</strong></p>
    </div>
    """
    return _send_email(subject, body_html, ticket.customer_email)
