import logging
import random
import string
import secrets
import uuid
from datetime import timedelta
from email.message import MIMEPart
from pathlib import Path

from django.db import transaction
from django.core import signing
from django.core.mail import EmailMessage, get_connection
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from core.models import EmailConfig
from account.models import OTPVerification, User
from core.constants import OTPPurpose

logger = logging.getLogger(__name__)

TEAM_LOGIN_OTP_EXPIRY_MINUTES = 15
TEAM_MANAGE_OTP_EXPIRY_MINUTES = 10
TEAM_INVITE_SIGNING_SALT = "right-route.team-driver-invite"
TEAM_INVITE_EXPIRY_DAYS = 1


def is_team_login_otp_expired(otp_object):
    """Return whether a Team Dashboard login OTP has expired."""
    return timezone.now() >= (
        otp_object.created_at + timedelta(minutes=TEAM_LOGIN_OTP_EXPIRY_MINUTES)
    )


def is_team_manage_otp_expired(otp_object):
    """Return whether a Team Dashboard email/password-change OTP has expired."""
    return timezone.now() >= (
        otp_object.created_at + timedelta(minutes=TEAM_MANAGE_OTP_EXPIRY_MINUTES)
    )


def mask_email_address(email):
    """
    Masks an email for display on verification screen.
    Example: johnd@glenbighaul.com -> j***d@glenbighaul.com
             chris@gmail.com -> c***s@gmail.com
    """
    if not email or "@" not in email:
        return email or ""

    user_part, domain = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = f"{user_part[0]}***"
    else:
        masked_user = f"{user_part[0]}***{user_part[-1]}"

    return f"{masked_user}@{domain}"


def generate_secure_password(length=12):
    """
    Generates a secure random password containing uppercase, lowercase, digits, and special characters.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in "!@#$%^&*" for c in password)):
            return password


def create_and_send_team_driver_invite(team, member):
    """Create a pending in-app driver invitation and send its email."""
    from account.emailsend import EmailInvitationLink
    from account.models import TeamMemberInvite

    invite = TeamMemberInvite.objects.create(
        team=team,
        team_member_object=member,
        invited_to=member.user,
        expires_at=timezone.now() + timedelta(days=TEAM_INVITE_EXPIRY_DAYS),
        queued_at=timezone.now(),
    )
    accept_link = build_team_invite_enrollment_link(invite)
    EmailInvitationLink(invite, accept_link, member.user.has_usable_password())
    invite.delivery_status = TeamMemberInvite.DeliveryStatus.SENT
    invite.invite_sent_at = timezone.now()
    invite.last_delivery_attempt_at = invite.invite_sent_at
    invite.delivery_attempt_count = 1
    invite.save(update_fields=[
        "delivery_status",
        "invite_sent_at",
        "last_delivery_attempt_at",
        "delivery_attempt_count",
        "updated_at",
    ])
    return invite


def build_team_invite_token(invite):
    """Return a timestamp-signed opaque token without exposing the invite UUID directly."""
    return signing.dumps(
        {"invite_id": str(invite.uuid)},
        salt=TEAM_INVITE_SIGNING_SALT,
        compress=True,
    )


def build_team_invite_enrollment_link(invite):
    token = build_team_invite_token(invite)
    frontend_url = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{frontend_url}/team/invite/{token}/accept"


def resolve_team_invite_token(token):
    """Resolve a signed invite token, retaining UUID compatibility for older clients."""
    try:
        payload = signing.loads(
            token,
            salt=TEAM_INVITE_SIGNING_SALT,
            max_age=timedelta(days=TEAM_INVITE_EXPIRY_DAYS),
        )
        return payload["invite_id"]
    except signing.SignatureExpired:
        raise
    except (signing.BadSignature, KeyError, TypeError):
        try:
            return str(uuid.UUID(str(token)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise signing.BadSignature("Invalid invitation token.") from exc


def queue_team_driver_invitation(team, member):
    """Durably enqueue one invitation and return (invite, newly_queued)."""
    from account.models import TeamMember, TeamMemberInvite
    from core.constants import TeamMemberInviteStatus

    now = timezone.now()
    with transaction.atomic():
        # Serialize concurrent clicks for this member even when no invite row
        # exists yet (select_for_update on an empty invite query locks nothing).
        TeamMember.objects.select_for_update().get(pk=member.pk, team=team)
        existing = (
            TeamMemberInvite.objects.select_for_update()
            .filter(
                team=team,
                team_member_object=member,
                invited_to=member.user,
                status=TeamMemberInviteStatus.PENDING,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if existing and existing.delivery_status in {
            TeamMemberInvite.DeliveryStatus.QUEUED,
            TeamMemberInvite.DeliveryStatus.SENDING,
            TeamMemberInvite.DeliveryStatus.SENT,
        }:
            return existing, False

        if existing:
            existing.delivery_status = TeamMemberInvite.DeliveryStatus.QUEUED
            existing.queued_at = now
            existing.delivery_failure_detail = ""
            existing.save(update_fields=[
                "delivery_status",
                "queued_at",
                "delivery_failure_detail",
                "updated_at",
            ])
            return existing, True

        invite = TeamMemberInvite.objects.create(
            team=team,
            team_member_object=member,
            invited_to=member.user,
            expires_at=now + timedelta(days=TEAM_INVITE_EXPIRY_DAYS),
            queued_at=now,
            delivery_status=TeamMemberInvite.DeliveryStatus.QUEUED,
        )
        return invite, True


def process_next_team_driver_invitation():
    """Claim and deliver one queued invitation. Returns False when the queue is empty."""
    from account.emailsend import EmailInvitationLink
    from account.models import TeamMemberInvite
    from core.constants import TeamMemberInviteStatus

    now = timezone.now()
    TeamMemberInvite.objects.filter(
        delivery_status=TeamMemberInvite.DeliveryStatus.QUEUED,
        expires_at__lte=now,
    ).update(
        status=TeamMemberInviteStatus.EXPIRED,
        delivery_status=TeamMemberInvite.DeliveryStatus.FAILED,
        delivery_failure_detail="Invitation expired before delivery.",
        updated_at=now,
    )
    TeamMemberInvite.objects.filter(
        delivery_status=TeamMemberInvite.DeliveryStatus.SENDING,
        last_delivery_attempt_at__lt=now - timedelta(minutes=15),
    ).update(
        delivery_status=TeamMemberInvite.DeliveryStatus.QUEUED,
        delivery_failure_detail="Previous delivery worker stopped before completion; requeued.",
        queued_at=now,
        updated_at=now,
    )
    with transaction.atomic():
        invite = (
            TeamMemberInvite.objects.select_for_update()
            .select_related("team", "team_member_object", "invited_to")
            .filter(
                delivery_status=TeamMemberInvite.DeliveryStatus.QUEUED,
                expires_at__gt=now,
            )
            .order_by("queued_at", "created_at")
            .first()
        )
        if not invite:
            return False
        invite.delivery_status = TeamMemberInvite.DeliveryStatus.SENDING
        invite.last_delivery_attempt_at = now
        invite.delivery_attempt_count += 1
        invite.save(update_fields=[
            "delivery_status",
            "last_delivery_attempt_at",
            "delivery_attempt_count",
            "updated_at",
        ])

    try:
        EmailInvitationLink(
            invite,
            build_team_invite_enrollment_link(invite),
            invite.invited_to.has_usable_password(),
        )
    except Exception as exc:
        logger.exception("Invitation delivery failed for invite %s", invite.pk)
        TeamMemberInvite.objects.filter(pk=invite.pk).update(
            delivery_status=TeamMemberInvite.DeliveryStatus.FAILED,
            delivery_failure_detail=str(exc)[:2000],
            updated_at=timezone.now(),
        )
        return True

    TeamMemberInvite.objects.filter(pk=invite.pk).update(
        delivery_status=TeamMemberInvite.DeliveryStatus.SENT,
        invite_sent_at=timezone.now(),
        delivery_failure_detail="",
        updated_at=timezone.now(),
    )
    return True


def _get_email_connection_and_sender():
    """Return a Django mail connection and sender from EmailConfig or EMAIL_* settings."""
    config = EmailConfig.objects.filter(is_active=True).first()
    if config:
        conn = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=config.host,
            port=int(config.port or 587),
            username=config.host_user,
            password=config.host_password,
            use_tls=config.tls,
            use_ssl=config.ssl,
            fail_silently=False,
        )
        sender = f"{config.name or 'RightRoute Support'} <{config.email}>"
        return conn, sender

    if not getattr(settings, "EMAIL_HOST", None):
        raise Exception("No active email configuration found.")
    if not getattr(settings, "EMAIL_HOST_USER", None) or not getattr(settings, "EMAIL_HOST_PASSWORD", None):
        raise Exception("SMTP email username/password are not configured.")

    conn = get_connection(
        backend=getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"),
        host=settings.EMAIL_HOST,
        port=int(getattr(settings, "EMAIL_PORT", 587)),
        username=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=getattr(settings, "EMAIL_USE_TLS", False),
        use_ssl=getattr(settings, "EMAIL_USE_SSL", False),
        fail_silently=False,
    )
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER)
    return conn, sender


def send_team_login_otp_email(user, otp_code):
    """
    Sends 6-digit MFA verification code to user's email for Team Dashboard login.
    """
    subject = f"RightRoute Team Dashboard Verification Code: {otp_code}"
    logo_path = Path(settings.BASE_DIR) / "static" / "logo.png"
    body_html = render_to_string(
        "team_dashboard/emails/login_verification.html",
        {
            "otp_code": otp_code,
            "expiry_minutes": TEAM_LOGIN_OTP_EXPIRY_MINUTES,
            "has_logo": logo_path.exists(),
            "support_email": "brad@getrightroute.app",
        },
    )

    try:
        conn, from_sender = _get_email_connection_and_sender()
        msg = EmailMessage(
            subject=subject,
            body=body_html,
            from_email=from_sender,
            to=[user.email],
            connection=conn,
        )
        msg.content_subtype = "html"
        if logo_path.exists():
            with logo_path.open("rb") as logo_file:
                logo_content = logo_file.read()
            logo = MIMEPart()
            logo.set_content(
                logo_content,
                maintype="image",
                subtype="png",
                disposition="inline",
                cid="<right-route-logo>",
                filename="right-route-logo.png",
            )
            msg.attach(logo)
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error(f"Failed to send team login OTP email to {user.email}: {e}")
        raise

def send_team_manage_otp_email(user, otp_code, action_label="account security"):
    """
    Sends 6-digit verification code to user's email for Manage (Email/Password change).
    """
    subject = f"RightRoute Verification Code for {action_label}: {otp_code}"
    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #ea580c;">RightRoute Security Verification</h2>
        <p>Hello,</p>
        <p>A request was received to update your <strong>{action_label}</strong> in the Team Dashboard.</p>
        <p>Your 6-digit verification code is:</p>
        <div style="background-color: #fff7ed; border: 2px dashed #ea580c; border-radius: 8px; padding: 16px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #c2410c;">{otp_code}</span>
        </div>
        <p>This code will expire in {TEAM_MANAGE_OTP_EXPIRY_MINUTES} minutes. If you did not make this request, please change your password immediately.</p>
        <p>Best regards,<br><strong>RightRoute Team</strong></p>
    </div>
    """

    try:
        conn, from_sender = _get_email_connection_and_sender()
        msg = EmailMessage(
            subject=subject,
            body=body_html,
            from_email=from_sender,
            to=[user.email],
            connection=conn,
        )
        msg.content_subtype = "html"
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error(f"Failed to send manage OTP email to {user.email}: {e}")
        raise

def generate_and_send_team_otp(user, request=None):
    """
    Creates a 6-digit OTP code for Login, persists it in OTPVerification, and sends verification email.
    """
    otp_code = str(random.randint(100000, 999999))
    
    # Invalidate old login OTPs for this user
    OTPVerification.objects.filter(
        user=user,
        purpose=OTPPurpose.LOGIN,
        is_verified=False,
    ).delete()

    ip_address = request.META.get("REMOTE_ADDR") if request else None
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""

    OTPVerification.objects.create(
        user=user,
        email=user.email,
        otp_code=otp_code,
        purpose=OTPPurpose.LOGIN,
        ip_address=ip_address,
        device_info=user_agent,
    )

    send_team_login_otp_email(user, otp_code)
    return otp_code


def generate_and_send_manage_otp(user, action_label="Email/Password Change", request=None):
    """
    Creates a 6-digit OTP code for Manage operations (Change Email / Change Password).
    """
    otp_code = str(random.randint(100000, 999999))

    ip_address = request.META.get("REMOTE_ADDR") if request else None
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""

    # Sending this endpoint again is the resend flow. Replace all previous
    # unused manage codes so that only the newest code can be accepted.
    with transaction.atomic():
        OTPVerification.objects.filter(
            user=user,
            purpose=OTPPurpose.RESET,
            is_verified=False,
        ).delete()

        OTPVerification.objects.create(
            user=user,
            email=user.email,
            otp_code=otp_code,
            purpose=OTPPurpose.RESET,
            ip_address=ip_address,
            device_info=user_agent,
        )

        # If SMTP fails, the transaction rolls back and does not leave a new
        # unusable code in the database.
        send_team_manage_otp_email(user, otp_code, action_label=action_label)
    return otp_code

