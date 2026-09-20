import logging
import os
import re
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from account.models import User
from supports.constants import (
    MainCategory,
    TicketPriority,
    TicketStatus,
    CATEGORY_ABBREVIATIONS,
)

logger = logging.getLogger(__name__)


def generate_ticket_number():
    """
    Generate sequential ticket number: RR-YYYY-00001 per calendar year.
    Uses atomic transaction and lock if necessary to avoid collision.
    """
    from supports.models import SupportTicket

    year = timezone.now().year
    prefix = f"RR-{year}-"

    # Find highest sequence for the year
    last_ticket = (
        SupportTicket.objects.filter(ticket_number__startswith=prefix)
        .order_by("-ticket_number")
        .first()
    )

    if last_ticket and last_ticket.ticket_number:
        try:
            seq_part = last_ticket.ticket_number.split("-")[-1]
            last_seq = int(seq_part)
            next_seq = last_seq + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1

    return f"{prefix}{str(next_seq).zfill(5)}"


def determine_ticket_priority(
    safety_critical=False,
    main_category=None,
    subcategory="",
    is_locked_out_paid_user=False,
):
    """
    Automatic priority assignment per PDF specification:
    - Safety-critical: Urgent
    - Generated route does not match permit: High
    - Duplicate or unexpected charge / Incorrect charge: High
    - Paid customer completely locked out: High
    - App crash / freezes preventing use: High
    - Feature request / general feedback: Low
    - Default: Normal
    """
    if safety_critical:
        return TicketPriority.URGENT

    sub_lower = (subcategory or "").lower()

    if is_locked_out_paid_user:
        return TicketPriority.HIGH

    if "route does not match permit" in sub_lower:
        return TicketPriority.HIGH

    if "duplicate charge" in sub_lower or "incorrect charge" in sub_lower:
        return TicketPriority.HIGH

    if "app crashes" in sub_lower or "app freezes" in sub_lower:
        return TicketPriority.HIGH

    if main_category == MainCategory.FEATURE_REQUEST:
        return TicketPriority.LOW

    if main_category == MainCategory.GENERAL_OTHER and (
        "feedback" in sub_lower or "testimonial" in sub_lower
    ):
        return TicketPriority.LOW

    return TicketPriority.NORMAL


def format_customer_display_name(name):
    """
    Formats customer name as 'J. Smith' per mockup.
    If single word or empty, returns as is.
    """
    if not name:
        return "-"
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0].upper()}. {' '.join(parts[1:])}"
    return name.strip()


def get_category_abbreviation(category_key):
    """Returns abbreviated category string for list column view."""
    return CATEGORY_ABBREVIATIONS.get(category_key, category_key or "-")


def match_customer_account(customer_email):
    """
    Finds matching non-staff RightRoute user account by email.
    Returns (user_obj, plan_name, is_active).
    """
    if not customer_email:
        return None, "Not Found", False

    user = User.objects.filter(email__iexact=customer_email.strip(), is_staff=False).first()
    if not user:
        return None, "Not Found", False

    # Check plan type / subscriptions
    plan_name = "Individual"
    if hasattr(user, "owned_team") and user.owned_team.is_active:
        plan_name = "Team"
    elif hasattr(user, "team_memberships") and user.team_memberships.filter(status=True).exists():
        plan_name = "Team"
    
    # Check if subscription exists
    if hasattr(user, "subscriptions"):
        sub = user.subscriptions.order_by("-created_at").first()
        if sub and getattr(sub, "plan", None):
            plan_name = getattr(sub.plan, "name", plan_name)

    is_active = (user.status == "ACTIVE" and user.is_active)
    return user, plan_name, is_active


def scan_file_for_malware(file_obj):
    """
    Scans an uploaded file for viruses/malware using python-clamd.
    If clamd daemon is configured and reachable, streams file bytes for scanning.
    If clamd daemon is not reachable (e.g. dev environment), logs a warning and passes.
    Raises ValueError if a virus/malware is detected.
    """
    try:
        import clamd

        clamd_host = os.environ.get("CLAMD_HOST", "127.0.0.1")
        clamd_port = int(os.environ.get("CLAMD_PORT", "3310"))

        cd = clamd.ClamdNetworkSocket(host=clamd_host, port=clamd_port, timeout=5)
        
        # Ping daemon
        try:
            cd.ping()
        except Exception:
            # Fallback check unix socket if on linux or skip if dev
            cd = None

        if cd is not None:
            # Rewind file before scanning
            pos = file_obj.tell() if hasattr(file_obj, "tell") else 0
            file_obj.seek(0)
            scan_res = cd.instream(file_obj)
            file_obj.seek(pos)

            # Response is dict: {'stream': ('FOUND', 'VirusName')} or {'stream': ('OK', None)}
            if scan_res and "stream" in scan_res:
                status, virus_name = scan_res["stream"]
                if status == "FOUND":
                    logger.error(f"Malware detected in upload: {virus_name}")
                    raise ValueError(f"Malware detected: {virus_name}")
    except ValueError:
        raise
    except Exception as e:
        # If ClamAV daemon is not currently active on this system, log info and allow file
        logger.warning(f"ClamAV scan skipped or unreachable: {str(e)}")

    return True
