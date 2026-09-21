import logging
import random
import string
import secrets
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone
from core.models import EmailConfig
from account.models import OTPVerification, User
from core.constants import OTPPurpose

logger = logging.getLogger(__name__)


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


def _get_email_connection():
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


def send_team_login_otp_email(user, otp_code):
    """
    Sends 6-digit MFA verification code to user's email for Team Dashboard login.
    """
    conn, config = _get_email_connection()
    if not conn or not config:
        logger.warning(f"No active EmailConfig. Team login verification code for {user.email}: {otp_code}")
        return False

    subject = f"RightRoute Team Dashboard Verification Code: {otp_code}"
    body_html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #ea580c;">RightRoute Team Dashboard</h2>
        <p>Hello,</p>
        <p>Your 6-digit verification code to log in to the Team Dashboard is:</p>
        <div style="background-color: #fff7ed; border: 2px dashed #ea580c; border-radius: 8px; padding: 16px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #c2410c;">{otp_code}</span>
        </div>
        <p>This code will expire in 5 minutes. If you did not request this code, please contact support at <a href="mailto:brad@getrightroute.app">brad@getrightroute.app</a>.</p>
        <p>Best regards,<br><strong>RightRoute Team</strong></p>
    </div>
    """

    try:
        from_sender = f"{config.name or 'RightRoute Support'} <{config.email}>"
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
        logger.error(f"Failed to send team login OTP email to {user.email}: {e}")
        return False


def send_team_manage_otp_email(user, otp_code, action_label="account security"):
    """
    Sends 6-digit verification code to user's email for Manage (Email/Password change).
    """
    conn, config = _get_email_connection()
    if not conn or not config:
        logger.warning(f"No active EmailConfig. Team manage verification code for {user.email} ({action_label}): {otp_code}")
        return False

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
        <p>This code will expire in 5 minutes. If you did not make this request, please change your password immediately.</p>
        <p>Best regards,<br><strong>RightRoute Team</strong></p>
    </div>
    """

    try:
        from_sender = f"{config.name or 'RightRoute Support'} <{config.email}>"
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
        return False


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

    # Invalidate old RESET OTPs for this user
    OTPVerification.objects.filter(
        user=user,
        purpose=OTPPurpose.RESET,
        is_verified=False,
    ).delete()

    ip_address = request.META.get("REMOTE_ADDR") if request else None
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""

    OTPVerification.objects.create(
        user=user,
        email=user.email,
        otp_code=otp_code,
        purpose=OTPPurpose.RESET,
        ip_address=ip_address,
        device_info=user_agent,
    )

    send_team_manage_otp_email(user, otp_code, action_label=action_label)
    return otp_code

