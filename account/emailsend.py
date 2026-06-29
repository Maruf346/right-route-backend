from core.models import EmailConfig
from django.core.mail import EmailMessage, get_connection
from django.conf import settings
from rest_framework.response import Response
from django.template.loader import render_to_string

# def LogInOTPSend(otp_object):
def EmailOTPSend(otp_object):
    email_config = EmailConfig.objects.filter(is_active=True).first()
    if not email_config:
        raise Exception("No active email configuration found.")
    
    email = otp_object.email
    otp = otp_object.otp_code
    
    subject = "Your OTP Code for Right Routes"
    context = {"otp": otp}
    html_message = render_to_string(
        "mail_template/otp_send.html",
        context,
    )
       
    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=email_config.host,
        port=int(email_config.port),
        username=email_config.host_user,
        password=email_config.host_password,
        use_tls=email_config.tls,
        fail_silently=False,
    )
    email_message = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=f"{email_config.name} <{email_config.email}>",
        to=[email],
        connection=connection,
    )
    email_message.content_subtype = "html"

    try:
        email_message.send()
        print(
            f"[OTP] Successfully sent OTP "
            f"{otp} to {email}"
        )
        return True
    except Exception as e:
        print(
            f"[OTP] Failed to send OTP "
            f"to {email}: {str(e)}"
        )
        raise Exception(
            f"Failed to send OTP: {str(e)}"
        )

def EmailInvitationLink(invite, accept_link, non_register_user):
    email_config = EmailConfig.objects.filter(is_active=True).first()
    if not email_config:
        raise Exception("No active email configuration found.")
    
    email = invite.invited_to
    
    subject = f"You've Been Invited to Join {invite.team.name} on Right Routes"
    context = {
        "team_name": invite.team.name,
        "invited_email": invite.invited_to.email,
        "accept_link": accept_link,
        "expires_at": invite.expires_at.strftime("%d %b %Y %I:%M %p"),
    }
    if non_register_user:
        html_message = render_to_string(
            "mail_template/user_invite.html",
            context,
        )
    else:
        html_message = render_to_string(
            "mail_template/user_invite_existing_user.html",
            context,
        )
    
    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=email_config.host,
        port=int(email_config.port),
        username=email_config.host_user,
        password=email_config.host_password,
        use_tls=email_config.tls,
        fail_silently=False,
    )
    email_message = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=f"{email_config.name} <{email_config.email}>",
        to=[email],
        connection=connection,
    )
    email_message.content_subtype = "html"

    try:
        email_message.send()
        print(
            f"Invitation Link Successfully sent to User Email "
        )
        return True
    except Exception as e:
        print(
            f"Invitation Link Failed sent to User Email "
        )
        raise Exception(
            f"Failed to send OTP: {str(e)}"
        )



