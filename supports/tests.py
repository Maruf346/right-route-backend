from django.core import mail
from django.test import TestCase, override_settings

from supports.constants import MainCategory
from supports.emails import send_staff_notification_email
from supports.models import SupportTicket
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
