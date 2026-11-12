from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from account.models import User
from core.constants import UserType
from security.views import TeamDataProtectionPrefillView
from team_dashboard.constants import TeamDashboardRole
from team_dashboard.models import TeamAdminProfile


class TeamDataProtectionPrefillTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(
            email="owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.user = User.objects.create_user(
            email="manager@example.com",
            password="ManagerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.profile = TeamAdminProfile.objects.create(
            user=self.user,
            team=owner.owned_team,
            role=TeamDashboardRole.ADMIN,
            full_name="Team Manager",
            phone=None,
            permissions_json=["security.data_protection"],
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def get_prefill_response(self):
        request = self.factory.get(
            "/api/v1/team-dashboard/security/data-protection/prefill/"
        )
        force_authenticate(request, user=self.user)
        return TeamDataProtectionPrefillView.as_view()(request)

    def test_missing_optional_phone_returns_empty_string(self):
        response = self.get_prefill_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Team Manager")
        self.assertEqual(response.data["phone_number"], "")

    def test_profile_phone_is_returned_as_phone_number(self):
        self.profile.phone = "+1 888 603 6317"
        self.profile.save(update_fields=["phone"])

        response = self.get_prefill_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone_number"], "+1 888 603 6317")
