class RequestOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = resolve_email_from_request(request)
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email=email)
            otp = str(random.randint(100000, 999999))
            user.otp_code = otp
            user.otp_created_at = timezone.now()
            user.save(update_fields=['otp_code', 'otp_created_at'])

            # Send OTP via HTML email
            subject = "Your OTP Code for SOCIALWIFI"
            html_message = f"""
            <html>
                <head>
                    <style>
                        body {{
                            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                            background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 50%, #fecfef 100%);
                            margin: 0;
                            padding: 20px;
                            color: #333;
                        }}
                        .container {{
                            max-width: 650px;
                            margin: auto;
                            background: #ffffff;
                            border-radius: 20px;
                            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.3);
                            overflow: hidden;
                            border: 2px solid #ff6b9d;
                        }}
                        .header {{
                            background: linear-gradient(135deg, #ff6b9d 0%, #c44569 100%);
                            padding: 40px 30px;
                            text-align: center;
                            color: #ffffff;
                            position: relative;
                        }}
                        .header h2 {{
                            margin: 0;
                            font-size: 32px;
                            font-weight: 700;
                            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
                        }}
                        .header .icon {{
                            font-size: 50px;
                            margin-bottom: 10px;
                        }}
                        .content {{
                            padding: 40px 30px;
                        }}
                        .otp-box {{
                            background: linear-gradient(135deg, #ff6b9d 0%, #c44569 100%);
                            padding: 25px;
                            border-radius: 15px;
                            text-align: center;
                            margin: 25px 0;
                            box-shadow: 0 5px 15px rgba(255, 107, 157, 0.4);
                            border: 3px solid #fff;
                        }}
                        .otp-code {{
                            font-size: 42px;
                            font-weight: bold;
                            color: #ffffff;
                            letter-spacing: 8px;
                            font-family: 'Courier New', monospace;
                            text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.5);
                        }}
                        .message {{
                            font-size: 18px;
                            color: #555;
                            line-height: 1.8;
                            margin: 20px 0;
                            text-align: center;
                        }}
                        .highlight {{
                            color: #ff6b9d;
                            font-weight: 700;
                            font-size: 20px;
                        }}
                        .warning {{
                            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
                            border-left: 6px solid #ffc107;
                            padding: 20px;
                            border-radius: 10px;
                            margin: 25px 0;
                            font-size: 16px;
                            color: #856404;
                            box-shadow: 0 3px 10px rgba(255, 193, 7, 0.2);
                        }}
                        .warning .icon {{
                            font-size: 24px;
                            margin-right: 10px;
                        }}
                        .footer {{
                            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                            padding: 30px;
                            text-align: center;
                            border-top: 2px solid #ff6b9d;
                        }}
                        .footer p {{
                            margin: 10px 0;
                            color: #666;
                            font-size: 16px;
                        }}
                        .footer strong {{
                            color: #ff6b9d;
                            font-size: 18px;
                        }}
                        .footer .social {{
                            margin-top: 20px;
                        }}
                        .footer .social a {{
                            margin: 0 10px;
                            text-decoration: none;
                            font-size: 24px;
                        }}
                        .cta-button {{
                            display: inline-block;
                            background: linear-gradient(135deg, #ff6b9d 0%, #c44569 100%);
                            color: #ffffff;
                            padding: 15px 30px;
                            border-radius: 25px;
                            text-decoration: none;
                            font-weight: bold;
                            font-size: 18px;
                            margin-top: 20px;
                            box-shadow: 0 5px 15px rgba(255, 107, 157, 0.4);
                        }}
                        .cta-button:hover {{
                            background: linear-gradient(135deg, #c44569 0%, #ff6b9d 100%);
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <div class="icon">🔐✨</div>
                            <h2>OTP Verification for SOCIALWIFI</h2>
                        </div>
                        <div class="content">
                            <p class="message">Hello <span class="highlight">{email}</span>,</p>
                            <p class="message">Thank you for choosing <span class="highlight">SOCIALWIFI</span>! 🌟 Your One-Time Password (OTP) for account verification is:</p>
                            
                            <div class="otp-box">
                                <div class="otp-code">{otp}</div>
                            </div>
                            
                            <p class="message">Please enter this code in the SOCIALWIFI app to login your account. This code is valid for <span class="highlight">15 minutes</span>. ⏰</p>
                            
                            <div class="warning">
                                <span class="icon">⚠️</span> <strong>Security Notice:</strong> Never share this code with anyone. SOCIALWIFI support will never ask for your OTP. Stay safe! 🛡️
                            </div>
                            
                            <p class="message">If you did not request this OTP, please ignore this email or contact our support team immediately. 📧</p>
                            
                            
                        </div>
                        <div class="footer">
                            <p>Thank you for using <strong>SOCIALWIFI</strong>! 💖</p>
                            <p>© 2025 SOCIALWIFI. All rights reserved.</p>
                            <p style="margin-top: 15px; color: #999; font-size: 14px;">This is an automated message. Please do not reply to this email.</p>
                            <div class="social">
                                <a href="#">📘</a>
                                <a href="#">🐦</a>
                                <a href="#">📷</a>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
            """
            
            # ✅ settings.DEFAULT_FROM_EMAIL ব্যবহার করুন (hardcoded email নয়)
            email_message = EmailMessage(
                subject=subject,
                body=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,  # ✅ এখানে পরিবর্তন করেছি
                to=[email],
            )
            email_message.content_subtype = "html"
            
            # ✅ Error handling যোগ করুন
            try:
                email_message.send(fail_silently=False)
                print(f"[OTP] ✅ Successfully sent OTP {otp} to {email}")
                return Response(
                    {"message": "OTP sent to email", "email": email}, 
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                print(f"[OTP] ❌ Failed to send OTP to {email}: {str(e)}")
                return Response(
                    {"error": f"Failed to send OTP: {str(e)}"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )


