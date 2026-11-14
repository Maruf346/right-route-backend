import os
import tempfile
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from account.models import User
from core.constants import UserType
from supports.constants import MainCategory
from supports.emails import send_staff_notification_email
from supports.models import SupportTicket, TicketAttachment
from supports.serializers import TeamSubmitTicketSerializer


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="smtp.example.com",
    EMAIL_PORT=587,
    EMAIL_HOST_USER="smtp-user@example.com",
    EMAIL_HOST_PASSWORD="test-password",
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    DEFAULT_FROM_EMAIL="RightRoute Support <smtp-user@example.com>",
)
class SupportStaffNotificationTests(TestCase):
    def test_staff_notification_uses_settings_fallback_and_help_recipient(self):
        ticket = SupportTicket.objects.create(
            ticket_number="RR-2026-00001",
            customer_name="Test Customer",
            customer_email="customer@example.com",
            main_category=MainCategory.GENERAL_OTHER,
            subject="Test support request",
            description="Testing staff support delivery.",
        )

        sent = send_staff_notification_email(ticket)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["help@getrightroute.app"])
        self.assertIn(ticket.ticket_number, mail.outbox[0].subject)
        self.assertIn(
            f"https://admin.getrightroute.app/dashboard/support-tickets/{ticket.id}",
            mail.outbox[0].body,
        )

    def test_team_ticket_submission_triggers_customer_and_staff_emails(self):
        serializer = TeamSubmitTicketSerializer(
            data={
                "name": "Test Customer",
                "account_email": "customer@example.com",
                "preferred_contact_method": "Email",
                "main_category": MainCategory.GENERAL_OTHER,
                "subject": "Team Dashboard support request",
                "description": "Please help with this test issue.",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        ticket = serializer.save()

        self.assertTrue(ticket.customer_confirmation_sent)
        self.assertTrue(ticket.staff_notification_sent)
        self.assertEqual(len(mail.outbox), 2)
        recipients = [recipient for message in mail.outbox for recipient in message.to]
        self.assertIn("customer@example.com", recipients)
        self.assertIn("help@getrightroute.app", recipients)

    def test_staff_notification_includes_ticket_screenshot(self):
        ticket = SupportTicket.objects.create(
            ticket_number="RR-2026-00002",
            customer_name="Screenshot Customer",
            customer_email="customer@example.com",
            main_category=MainCategory.APP_TECHNICAL,
            subject="Screenshot support request",
            description="The screenshot should be attached to the staff email.",
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            TicketAttachment.objects.create(
                ticket=ticket,
                file=SimpleUploadedFile(
                    "dashboard-error.png",
                    b"test screenshot bytes",
                    content_type="image/png",
                ),
                original_filename="dashboard-error.png",
                file_size=21,
                file_type="png",
            )

            sent = send_staff_notification_email(ticket)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0][0], "dashboard-error.png")
        self.assertEqual(mail.outbox[0].attachments[0][1], b"test screenshot bytes")
        self.assertEqual(mail.outbox[0].attachments[0][2], "image/png")

    @patch("supports.serializers.scan_file_for_malware", return_value=True)
    @patch("supports.serializers.send_staff_notification_email", return_value=True)
    @patch("supports.serializers.send_customer_confirmation_email", return_value=True)
    def test_team_submission_persists_multipart_screenshot(
        self,
        _mocked_customer_email,
        _mocked_staff_email,
        _mocked_scan,
    ):
        owner = User.objects.create_user(
            email="support-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        client = APIClient()
        client.force_authenticate(owner)
        screenshot = SimpleUploadedFile(
            "dashboard-error.png",
            b"test screenshot bytes",
            content_type="image/png",
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = client.post(
                reverse("team-dashboard-support-submit-ticket"),
                {
                    "name": "Support Owner",
                    "account_email": owner.email,
                    "main_category": MainCategory.APP_TECHNICAL,
                    "subject": "Screenshot upload test",
                    "description": "The screenshot must be stored with this ticket.",
                    "uploaded_files": [screenshot],
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["attachment_count"], 1)
            attachment = TicketAttachment.objects.get(ticket_id=response.data["ticket_id"])
            self.assertEqual(attachment.original_filename, "dashboard-error.png")
            self.assertTrue(os.path.exists(attachment.file.path))

    @patch("supports.serializers.scan_file_for_malware", return_value=True)
    @patch("supports.serializers.send_staff_notification_email", return_value=True)
    @patch("supports.serializers.send_customer_confirmation_email", return_value=True)
    def test_team_submission_accepts_screenshot_alias(
        self,
        _mocked_customer_email,
        _mocked_staff_email,
        _mocked_scan,
    ):
        owner = User.objects.create_user(
            email="support-alias@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        client = APIClient()
        client.force_authenticate(owner)

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = client.post(
                reverse("team-dashboard-support-submit-ticket"),
                {
                    "name": "Support Alias",
                    "account_email": owner.email,
                    "main_category": MainCategory.APP_TECHNICAL,
                    "subject": "Screenshot alias test",
                    "description": "Accept common screenshot multipart field names.",
                    "screenshot": SimpleUploadedFile("alias.png", b"alias", content_type="image/png"),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["attachment_count"], 1)
