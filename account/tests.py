from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from account.models import OTPVerification, User
from core.constants import UserType

CONTINUE_URL = "/api/v1/auth/continue/"
LOGIN_URL = "/api/v1/auth/login/"


@override_settings(SECURE_SSL_REDIRECT=False)
@patch("account.views.EmailOTPSend")
class ContinueLoginFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _make_user(self, email, verified):
        user = User.objects.create_user(
            email=email,
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        user.is_email_verified = verified
        user.save(update_fields=["is_email_verified"])
        return user

    def test_verified_user_skips_otp_and_logs_in_with_password(self, mock_send):
        self._make_user("verified@example.com", verified=True)

        res = self.client.post(CONTINUE_URL, {"email": "Verified@Example.com"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["is_registered"])
        self.assertEqual(res.data["next_step"], "SUBMIT_PASSWORD")
        mock_send.assert_not_called()
        self.assertFalse(OTPVerification.objects.filter(email="verified@example.com").exists())

        res = self.client.post(
            LOGIN_URL,
            {"email": "verified@example.com", "password": "DriverPass123!"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data["data"])

    def test_unverified_user_still_gets_otp(self, mock_send):
        self._make_user("unverified@example.com", verified=False)

        res = self.client.post(CONTINUE_URL, {"email": "unverified@example.com"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["next_step"], "OTP_VERIFY")
        mock_send.assert_called_once()

    def test_new_email_goes_to_create_password(self, mock_send):
        res = self.client.post(CONTINUE_URL, {"email": "new@example.com"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["is_registered"])
        self.assertEqual(res.data["next_step"], "CREATE_PASSWORD")
        mock_send.assert_not_called()
