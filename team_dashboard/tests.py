from unittest.mock import patch
from types import SimpleNamespace

from django.core import mail
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from account.models import OTPVerification, Team, TeamMember, User
from account.emailsend import EmailInvitationLink
from core.constants import OTPPurpose, UserType
from team_dashboard.constants import TeamDashboardRole
from team_dashboard.models import TeamAdminProfile
from team_dashboard.serializers import (
    TeamLoginRequestSerializer,
    TeamVerifyOTPRequestSerializer,
)
from route.models import PermitWaypoint, Route, RoutePermit


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="mailer@example.com",
    EMAIL_HOST_PASSWORD="test-password",
    DEFAULT_FROM_EMAIL="RightRoute <mailer@example.com>",
    IOS_APP_STORE_URL="https://apps.apple.com/example",
    GOOGLE_PLAY_STORE_URL="https://play.google.com/store/apps/details?id=com.rightroutes.running",
)
class TeamDriverInvitationEmailTests(TestCase):
    def test_invitation_uses_requested_content_links_and_embedded_store_badges(self):
        invite = SimpleNamespace(
            invited_to=SimpleNamespace(email="driver@example.com"),
            team=SimpleNamespace(name="Acme Hauling"),
            team_member_object=SimpleNamespace(username="Jane Driver"),
        )

        self.assertTrue(EmailInvitationLink(invite))

        message = mail.outbox[0]
        self.assertIn("Hello Jane Driver,", message.body)
        self.assertIn("join the Acme Hauling Team", message.body)
        self.assertIn("https://youtu.be/QVbbLaTovho", message.body)
        self.assertIn("https://youtu.be/Yqlv0VveXI4", message.body)
        self.assertIn("https://getrightroute.app/Team-Fleet-Driver-User-Guide.pdf", message.body)
        self.assertIn('href="https://apps.apple.com/example"', message.body)
        self.assertIn(
            'href="https://play.google.com/store/apps/details?id=com.rightroutes.running"',
            message.body,
        )
        self.assertIn('src="cid:app-store-badge"', message.body)
        self.assertIn('src="cid:google-play-badge"', message.body)
        self.assertEqual(
            {attachment.get_filename() for attachment in message.attachments},
            {"app-store.svg", "google-play.svg"},
        )


class LockedTeamAdminLoginTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        # MAIN_USER creation automatically creates an owned team via signal.
        self.team = self.owner.owned_team
        self.team.name = "Test Hauling"
        self.team.save(update_fields=["name"])
        self.admin = User.objects.create_user(
            email="limited-admin@example.com",
            password="AdminPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.profile = TeamAdminProfile.objects.create(
            user=self.admin,
            team=self.team,
            role=TeamDashboardRole.ADMIN,
            permissions_json=["manage.team_users"],
            is_active=False,
        )

        # This automatically-created personal team was the original bypass:
        # access lookup treated the locked sub-admin as its owner and granted
        # every Team Dashboard permission.
        self.assertTrue(hasattr(self.admin, "owned_team"))

        # Reproduce the dangerous fallback: the locked admin is also present
        # in the team driver/member list.
        TeamMember.objects.create(
            team=self.team,
            user=self.admin,
            username="Limited Admin",
            status=True,
        )

    def test_locked_admin_cannot_pass_password_login(self):
        serializer = TeamLoginRequestSerializer(
            data={
                "email": self.admin.email,
                "password": "AdminPass123!",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("locked or inactive", str(serializer.errors).lower())

    def test_locked_admin_cannot_complete_login_with_existing_otp(self):
        OTPVerification.objects.create(
            user=self.admin,
            email=self.admin.email,
            otp_code="123456",
            purpose=OTPPurpose.LOGIN,
        )
        serializer = TeamVerifyOTPRequestSerializer(
            data={"email": self.admin.email, "otp_code": "123456"}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("locked or inactive", str(serializer.errors).lower())


class TeamRouteManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="route-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.team = self.owner.owned_team
        self.team.name = "Route Team"
        self.team.save(update_fields=["name"])
        self.driver = User.objects.create_user(
            email="driver@example.com",
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        TeamMember.objects.create(team=self.team, user=self.driver, username="Driver", status=True)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_create_route_accepts_continuous_nested_permits(self):
        payload = {
            "name": "Nebraska to Iowa",
            "start_location": "Lincoln, NE",
            "start_latitude": 40.8136,
            "start_longitude": -96.7026,
            "end_location": "Des Moines, IA",
            "end_latitude": 41.5868,
            "end_longitude": -93.625,
            "permits": [
                {
                    "index": 1,
                    "name": "Permit 1",
                    "issuing_state": "NE",
                    "start_location": "Lincoln, NE",
                    "start_latitude": 40.8136,
                    "start_longitude": -96.7026,
                    "end_location": "State Border",
                    "end_latitude": 41.2619,
                    "end_longitude": -95.8608,
                    "waypoints": [{
                        "name": "US-77 NB",
                        "latitude": 41.0,
                        "longitude": -96.5,
                    }],
                },
                {
                    "index": 2,
                    "name": "Permit 2",
                    "issuing_state": "IA",
                    "start_location": "State Border",
                    "start_latitude": 41.2619,
                    "start_longitude": -95.8608,
                    "end_location": "Des Moines, IA",
                    "end_latitude": 41.5868,
                    "end_longitude": -93.625,
                    "waypoints": [],
                },
            ],
        }

        response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver.id}),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        route = Route.objects.get(id=response.data["route_id"])
        self.assertEqual(route.permits.count(), 2)
        self.assertEqual(list(route.permits.values_list("issuing_state", flat=True)), ["NE", "IA"])

    def test_create_route_rejects_disconnected_permits(self):
        payload = {
            "start_location": "Lincoln, NE",
            "start_latitude": 40.8136,
            "start_longitude": -96.7026,
            "end_location": "Des Moines, IA",
            "end_latitude": 41.5868,
            "end_longitude": -93.625,
            "permits": [
                {
                    "index": 1,
                    "start_location": "Lincoln",
                    "start_latitude": 40.8136,
                    "start_longitude": -96.7026,
                    "end_location": "Border",
                    "end_latitude": 41.2619,
                    "end_longitude": -95.8608,
                },
                {
                    "index": 2,
                    "start_location": "Wrong point",
                    "start_latitude": 42.0,
                    "start_longitude": -95.0,
                    "end_location": "Des Moines",
                    "end_latitude": 41.5868,
                    "end_longitude": -93.625,
                },
            ],
        }
        response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver.id}),
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("must match", str(response.data))

    def test_waypoint_insert_and_delete_keep_contiguous_order(self):
        route = Route.objects.create(created_by=self.driver, team=self.team, name="Route")
        permit = RoutePermit.objects.create(
            route=route,
            index=1,
            start_location="A",
            start_latitude=40,
            start_longitude=-96,
            end_location="B",
            end_latitude=41,
            end_longitude=-95,
        )
        first = PermitWaypoint.objects.create(
            permit=permit, route=route, index=1, name="First", latitude=40.1, longitude=-95.9
        )
        second = PermitWaypoint.objects.create(
            permit=permit, route=route, index=2, name="Second", latitude=40.2, longitude=-95.8
        )
        create_url = reverse(
            "team-route-permit-waypoint-create",
            kwargs={"route_id": route.id, "permit_id": permit.id},
        )
        response = self.client.post(
            create_url,
            {"index": 2, "name": "Inserted", "latitude": 40.15, "longitude": -95.85},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            list(permit.waypoints.order_by("index").values_list("name", "index")),
            [("First", 1), ("Inserted", 2), ("Second", 3)],
        )

        move_url = reverse(
            "team-route-permit-waypoint-detail",
            kwargs={"route_id": route.id, "permit_id": permit.id, "waypoint_id": second.id},
        )
        response = self.client.patch(move_url, {"index": 1}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            list(permit.waypoints.order_by("index").values_list("name", "index")),
            [("Second", 1), ("First", 2), ("Inserted", 3)],
        )

        delete_url = reverse(
            "team-route-permit-waypoint-detail",
            kwargs={"route_id": route.id, "permit_id": permit.id, "waypoint_id": first.id},
        )
        response = self.client.delete(delete_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            list(permit.waypoints.order_by("index").values_list("name", "index")),
            [("Second", 1), ("Inserted", 2)],
        )

    @patch("route.service.parse_permit_route")
    def test_parse_endpoint_returns_state_bounded_schema(self, mocked_parse):
        mocked_parse.return_value = {
            "status": "success",
            "permit_number": "NE-1",
            "issuing_state": "NE",
            "origin": {"name": "Lincoln, NE", "latitude": 40.8, "longitude": -96.7},
            "destination": {"name": "Fremont, NE", "latitude": 41.4, "longitude": -96.5},
            "waypoints": [],
            "unresolved_waypoints": [],
        }
        response = self.client.post(
            reverse("team-permit-parse"),
            {"permit_text": "Nebraska DOT from Lincoln to Fremont", "state_hint": "NE"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["issuing_state"], "NE")


class TeamUserManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="members-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.team = self.owner.owned_team
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _member(self, email, status):
        user = User.objects.create_user(
            email=email,
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        return TeamMember.objects.create(
            team=self.team,
            user=user,
            username=email.split("@", 1)[0],
            status=status,
        )

    def test_enrolled_yes_and_no_filters(self):
        self._member("enrolled@example.com", True)
        self._member("pending@example.com", False)
        url = reverse("team-users-list")

        enrolled_response = self.client.get(url, {"enrolled": "yes"})
        pending_response = self.client.get(url, {"enrolled": "no"})

        self.assertEqual(enrolled_response.status_code, 200)
        self.assertEqual(
            [item["email"] for item in enrolled_response.data["results"]],
            ["enrolled@example.com"],
        )
        self.assertEqual(
            [item["email"] for item in pending_response.data["results"]],
            ["pending@example.com"],
        )

    @patch("team_dashboard.views.create_and_send_team_driver_invite")
    def test_csv_import_supports_bom_and_first_last_name_headers(self, mocked_invite):
        content = "\ufeffFirst Name,Last Name,Email\r\nJane,Doe,JANE@example.com\r\n"
        upload = SimpleUploadedFile(
            "drivers.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("team-users-import-csv"),
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["added_count"], 1)
        member = TeamMember.objects.get(team=self.team, user__email="jane@example.com")
        self.assertEqual(member.username, "Jane Doe")
        mocked_invite.assert_called_once()

    @patch("team_dashboard.views.create_and_send_team_driver_invite")
    def test_manual_add_sends_invite(self, mocked_invite):
        response = self.client.post(
            reverse("team-users-list"),
            {"users": [{"name": "New Driver", "email": "new-driver@example.com"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["added_count"], 1)
        mocked_invite.assert_called_once()

    @patch("team_dashboard.views.create_and_send_team_driver_invite")
    def test_smtp_failure_rolls_back_new_member_for_retry(self, mocked_invite):
        mocked_invite.side_effect = RuntimeError("SMTP unavailable")
        response = self.client.post(
            reverse("team-users-list"),
            {"users": [{"name": "Retry Driver", "email": "retry@example.com"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 502, response.data)
        self.assertFalse(TeamMember.objects.filter(team=self.team, user__email="retry@example.com").exists())

