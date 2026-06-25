from core.models import EmailConfig
from django.core.mail import EmailMessage, get_connection
from django.conf import settings
from rest_framework.response import Response


# def LogInOTPSend(otp_object):
def EmailOTPSend(otp_object):
    email_config = EmailConfig.objects.filter(is_active=True).first()
    if not email_config:
        raise Exception("No active email configuration found.")
    
    email = otp_object.email
    otp = otp_object.otp_code
    
    subject = "Your OTP Code for Right Routes"
    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>OTP Verification</title>
    </head>
    <body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,Helvetica,sans-serif;">

        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f7fb;padding:30px 0;">
            <tr>
                <td align="center">

                    <table width="650" cellpadding="0" cellspacing="0"
                        style="background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.12);">
                        <!-- Content -->
                        <tr>
                            <td style="padding:40px 35px;">

                                <p style="font-size:18px;color:#374151;">
                                    Hello,
                                </p>

                                <p style="font-size:17px;line-height:1.8;color:#4b5563;">
                                    We received a request to verify your account.
                                    Use the following One-Time Password (OTP)
                                    to continue.
                                </p>

                                <!-- OTP BOX -->
                                <div style="
                                    background:linear-gradient(135deg,#2563eb,#06b6d4);
                                    border-radius:18px;
                                    text-align:center;
                                    padding:30px;
                                    margin:35px 0;
                                    box-shadow:0 10px 25px rgba(37,99,235,0.25);
                                ">
                                    <div style="
                                        color:white;
                                        font-size:44px;
                                        font-weight:bold;
                                        letter-spacing:10px;
                                        font-family:Courier New, monospace;
                                    ">
                                        {otp}
                                    </div>
                                </div>

                                <p style="
                                    text-align:center;
                                    color:#1e40af;
                                    font-size:18px;
                                    font-weight:600;
                                ">
                                    OTP expires in 15 minutes
                                </p>

                                <!-- Warning -->
                                <div style="
                                    background:#fff7ed;
                                    border-left:5px solid #f97316;
                                    padding:18px;
                                    border-radius:10px;
                                    margin-top:30px;
                                ">
                                    <strong style="color:#c2410c;">
                                        Security Notice
                                    </strong>

                                    <p style="
                                        margin-top:10px;
                                        color:#7c2d12;
                                        line-height:1.7;
                                    ">
                                        Never share this OTP with anyone.
                                        Right Routes support team will never ask
                                        for your verification code.
                                    </p>
                                </div>

                                <p style="
                                    margin-top:30px;
                                    color:#6b7280;
                                    line-height:1.8;
                                ">
                                    If you did not request this OTP,
                                    you can safely ignore this email.
                                </p>

                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td align="center"
                                style="background:#f8fafc;padding:30px;border-top:1px solid #e5e7eb;">

                                <h3 style="
                                    margin:0;
                                    color:#0f172a;
                                ">
                                    Right Routes
                                </h3>

                                <p style="
                                    margin-top:10px;
                                    color:#64748b;
                                    font-size:14px;
                                ">
                                    Secure Route Navigation & Permit Management
                                </p>

                                <p style="
                                    margin-top:15px;
                                    color:#94a3b8;
                                    font-size:13px;
                                ">
                                    © 2026 Right Routes. All Rights Reserved.
                                </p>

                                <p style="
                                    color:#94a3b8;
                                    font-size:12px;
                                ">
                                    This is an automated email. Please do not reply.
                                </p>

                            </td>
                        </tr>

                    </table>

                </td>
            </tr>
        </table>

    </body>
    </html>
    """
    
    emaildata = {
        "host": email_config.host,
        "port": email_config.port,
        "tls": email_config.tls,
        "host_user": email_config.email,
        "host_password": email_config.host_password,
        "email": email_config.email,
        "name": email_config.name,
    }
    print("emaildata: ", emaildata)
    
    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=email_config.host,
        port=int(email_config.port),
        username=email_config.email,
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

