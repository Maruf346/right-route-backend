from unittest.mock import patch
from types import SimpleNamespace

from django.core import mail
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from account.models import OTPVerification, Team, TeamMember, TeamMemberInvite, User
from account.emailsend import EmailInvitationLink
from core.constants import OTPPurpose, UserType
from team_dashboard.constants import TeamDashboardRole
from team_dashboard.models import TeamAdminProfile
from team_dashboard.utils import build_team_invite_token, process_next_team_driver_invitation
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

        self.assertTrue(EmailInvitationLink(invite, "https://team.example.com/enroll/signed-token"))

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
        self.assertIn('href="https://team.example.com/enroll/signed-token"', message.body)
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
        self.driver_c = User.objects.create_user(
            email="driver-c@example.com",
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _flat_route_payload(self, name="Dashboard Draft"):
        return {
            "name": name,
            "start_location": "Lincoln, NE",
            "start_latitude": 40.8136,
            "start_longitude": -96.7026,
            "end_location": "Omaha, NE",
            "end_latitude": 41.2565,
            "end_longitude": -95.9345,
        }

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
                    "permit_number": "P-100",
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
                    "permit_number": "P-200",
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
        self.assertEqual(route.user_id, self.driver.id)
        self.assertEqual(route.created_by_id, self.owner.id)
        self.assertEqual(route.status, "DRAFT")
        self.assertEqual(route.permits.count(), 2)
        self.assertEqual(list(route.permits.values_list("issuing_state", flat=True)), ["NE", "IA"])
        self.assertEqual(list(route.permits.values_list("permit_number", flat=True)), ["P-100", "P-200"])
        self.assertEqual(route.permits.get(index=1).waypoints.count(), 1)
        self.assertEqual(route.permits.get(index=2).waypoints.count(), 0)

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
        route = Route.objects.create(user=self.driver, created_by=self.driver, team=self.team, name="Route")
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

    @patch("route.service.get_intersection_lat_lng")
    @patch("route.service._geocode_named_location")
    @patch("route.service.extract_route_data")
    def test_parse_two_files_sequentially_keeps_second_result_isolated(
        self,
        mocked_extract,
        mocked_geocode,
        mocked_intersections,
    ):
        mocked_extract.side_effect = [
            {
                "permit_number": "P-100",
                "issuing_state": "NE",
                "origin": "First Origin",
                "destination": "First Destination",
                "waypoints": ["US-30 EB"],
            },
            {
                "permit_number": "P-200",
                "issuing_state": "IA",
                "origin": "Second Origin",
                "destination": "Second Destination",
                "waypoints": ["IA-92 EB", "Unmapped IA Road"],
            },
        ]
        locations = {
            "First Origin": (41.1, -97.1),
            "First Destination": (41.8, -96.2),
            "Second Origin": (41.2, -95.9),
            "Second Destination": (41.6, -94.8),
        }
        mocked_geocode.side_effect = lambda name, _state: {
            "name": name,
            "latitude": locations[name][0],
            "longitude": locations[name][1],
        }
        mocked_intersections.side_effect = [
            [{"name": "US-30 EB", "lat": 41.3, "lng": -96.9}],
            [{"name": "IA-92 EB", "lat": 41.4, "lng": -95.2}],
        ]

        first_response = self.client.post(
            reverse("team-permit-parse"),
            {"file": SimpleUploadedFile("permit-one.pdf", b"first", content_type="application/pdf")},
            format="multipart",
        )
        second_response = self.client.post(
            reverse("team-permit-parse"),
            {"file": SimpleUploadedFile("permit-two.pdf", b"second", content_type="application/pdf")},
            format="multipart",
        )

        self.assertEqual(first_response.status_code, 200, first_response.data)
        self.assertEqual(second_response.status_code, 200, second_response.data)
        self.assertEqual(second_response.data["permit_number"], "P-200")
        self.assertEqual(second_response.data["issuing_state"], "IA")
        self.assertEqual([item["name"] for item in second_response.data["waypoints"]], ["IA-92 EB"])
        self.assertEqual(second_response.data["unresolved_waypoints"], ["Unmapped IA Road"])
        self.assertNotIn("P-100", str(second_response.data))
        self.assertNotIn("US-30 EB", str(second_response.data))

    @patch("route.service.parse_permit_route")
    def test_parse_rejects_non_finite_coordinates(self, mocked_parse):
        mocked_parse.return_value = {
            "status": "success",
            "permit_number": "P-BAD",
            "issuing_state": "NE",
            "origin": {"name": "Origin", "latitude": float("nan"), "longitude": -97.1},
            "destination": None,
            "waypoints": [],
            "unresolved_waypoints": [],
        }

        response = self.client.post(
            reverse("team-permit-parse"),
            {"permit_text": "Nebraska DOT permit"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)

    @patch("route.service.extract_route_data")
    def test_parse_failure_returns_non_success_status(self, mocked_extract):
        mocked_extract.side_effect = ValidationError("Permit OCR extraction failed.")

        response = self.client.post(
            reverse("team-permit-parse"),
            {"file": SimpleUploadedFile("broken.pdf", b"broken", content_type="application/pdf")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)

    def test_dashboard_created_draft_is_visible_to_driver_and_team_history_only(self):
        create_response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver.id}),
            self._flat_route_payload(),
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        route_id = create_response.data["route_id"]

        self.client.force_authenticate(self.driver)
        driver_response = self.client.get(reverse("route-list"))
        self.assertEqual(driver_response.status_code, 200, driver_response.data)
        self.assertIn(route_id, [route["id"] for route in driver_response.data["data"]])

        self.client.force_authenticate(self.driver_c)
        driver_c_response = self.client.get(reverse("route-list"))
        self.assertNotIn(route_id, [route["id"] for route in driver_c_response.data["data"]])

        self.client.force_authenticate(self.owner)
        history_response = self.client.get(
            reverse("team-route-history-list"),
            {"user_id": self.driver.id},
        )
        self.assertEqual(history_response.status_code, 200, history_response.data)
        self.assertIn(route_id, [route["id"] for route in history_response.data])

        other_owner = User.objects.create_user(
            email="other-route-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.client.force_authenticate(other_owner)
        other_history = self.client.get(reverse("team-route-history-list"))
        self.assertNotIn(route_id, [route["id"] for route in other_history.data])

    def test_create_route_rejects_user_outside_team(self):
        response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver_c.id}),
            self._flat_route_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 404, response.data)
        self.assertFalse(Route.objects.filter(user=self.driver_c).exists())

    def test_create_route_rejects_unenrolled_member(self):
        TeamMember.objects.create(
            team=self.team,
            user=self.driver_c,
            username="Driver C",
            status=False,
        )

        response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver_c.id}),
            self._flat_route_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(Route.objects.filter(user=self.driver_c).exists())

    @patch("team_dashboard.views._create_or_update_permit")
    def test_nested_save_failure_rolls_back_route(self, mocked_permit_save):
        mocked_permit_save.side_effect = ValidationError({"waypoints": "Invalid nested waypoint."})

        response = self.client.post(
            reverse("team-driver-route-create", kwargs={"user_id": self.driver.id}),
            self._flat_route_payload("Must Roll Back"),
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Route.objects.filter(name="Must Roll Back").exists())


class TeamUserManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="members-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.team = self.owner.owned_team
        self.team.max_members = 100
        self.team.save(update_fields=["max_members"])
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _member(self, email, status, name=None):
        user = User.objects.create_user(
            email=email,
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        return TeamMember.objects.create(
            team=self.team,
            user=user,
            username=name or email.split("@", 1)[0],
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

    def test_first_name_ordering_is_applied_before_pagination(self):
        self._member("zoe@example.com", False, "Zoe Zebra")
        self._member("amy@example.com", False, "Amy Able")
        self._member("mike@example.com", False, "Mike Middle")

        first_page = self.client.get(
            reverse("team-users-list"),
            {"ordering": "first_name", "page": 1, "page_size": 2},
        )
        second_page = self.client.get(
            reverse("team-users-list"),
            {"ordering": "first_name", "page": 2, "page_size": 2},
        )

        self.assertEqual([item["name"] for item in first_page.data["results"]], ["Amy Able", "Mike Middle"])
        self.assertEqual([item["name"] for item in second_page.data["results"]], ["Zoe Zebra"])

    def test_csv_import_supports_bom_and_first_last_name_headers(self):
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
        self.assertFalse(TeamMemberInvite.objects.filter(team=self.team).exists())

    def test_manual_batch_add_does_not_send_invite(self):
        response = self.client.post(
            reverse("team-users-list"),
            {"users": [{"name": "New Driver", "email": "new-driver@example.com"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["added_count"], 1)
        self.assertFalse(TeamMemberInvite.objects.filter(team=self.team).exists())

    def test_csv_sized_batch_add_creates_every_valid_row_atomically(self):
        users = [
            {"name": f"Driver {index:02d}", "email": f"driver-{index:02d}@example.com"}
            for index in range(25)
        ]

        response = self.client.post(reverse("team-users-list"), {"users": users}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["added_count"], 25)
        self.assertEqual(TeamMember.objects.filter(team=self.team).count(), 25)
        self.assertFalse(TeamMemberInvite.objects.filter(team=self.team).exists())

    def test_batch_add_rejects_duplicate_email_without_partial_writes(self):
        self._member("existing@example.com", False)
        response = self.client.post(
            reverse("team-users-list"),
            {
                "users": [
                    {"name": "New Driver", "email": "new@example.com"},
                    {"name": "Existing Driver", "email": "existing@example.com"},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(TeamMember.objects.filter(team=self.team, user__email="new@example.com").exists())

    def test_batch_add_enforces_plan_capacity(self):
        self.team.max_members = 1
        self.team.save(update_fields=["max_members"])
        self._member("existing@example.com", False)

        response = self.client.post(
            reverse("team-users-list"),
            {"users": [{"name": "Over Limit", "email": "over@example.com"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)

    def test_send_invite_is_owner_only_and_idempotent(self):
        first = self._member("first@example.com", False, "First Driver")
        second = self._member("second@example.com", False, "Second Driver")
        url = reverse("team-users-send-invite")

        first_response = self.client.post(url, {"member_ids": [first.id, second.id]}, format="json")
        repeated_response = self.client.post(url, {"member_ids": [first.id, second.id]}, format="json")

        self.assertEqual(first_response.status_code, 200, first_response.data)
        self.assertEqual(first_response.data["queued_count"], 2)
        self.assertEqual(repeated_response.status_code, 200, repeated_response.data)
        self.assertEqual(repeated_response.data["queued_count"], 0)
        self.assertEqual(repeated_response.data["idempotent_count"], 2)
        self.assertEqual(TeamMemberInvite.objects.filter(team=self.team).count(), 2)

    def test_signed_invitation_token_can_be_accepted(self):
        member = self._member("signed-invite@example.com", False, "Signed Driver")
        queue_response = self.client.post(
            reverse("team-users-send-invite"),
            {"member_ids": [member.id]},
            format="json",
        )
        self.assertEqual(queue_response.status_code, 200, queue_response.data)
        invite = TeamMemberInvite.objects.get(team_member_object=member)
        token = build_team_invite_token(invite)
        self.assertNotIn(str(invite.uuid), token)

        self.client.force_authenticate(member.user)
        accept_response = self.client.post(
            reverse("invitation-action"),
            {"invitation_uuid": token, "action": "ACCEPT"},
            format="json",
        )

        self.assertEqual(accept_response.status_code, 200, accept_response.data)
        member.refresh_from_db()
        self.assertTrue(member.status)

    def test_send_invite_rejects_foreign_member_id(self):
        other_owner = User.objects.create_user(
            email="other-owner@example.com",
            password="OwnerPass123!",
            user_type=UserType.MAIN_USER,
        )
        other_team = other_owner.owned_team
        foreign_user = User.objects.create_user(
            email="foreign-driver@example.com",
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        foreign_member = TeamMember.objects.create(
            team=other_team,
            user=foreign_user,
            username="Foreign Driver",
            status=False,
        )

        response = self.client.post(
            reverse("team-users-send-invite"),
            {"member_ids": [foreign_member.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.data)

    def test_send_invite_rejects_non_owner_with_manage_permission(self):
        member = self._member("pending-owner-only@example.com", False)
        admin = User.objects.create_user(
            email="team-admin@example.com",
            password="AdminPass123!",
            user_type=UserType.MAIN_USER,
        )
        TeamAdminProfile.objects.create(
            user=admin,
            team=self.team,
            role=TeamDashboardRole.ADMIN,
            permissions_json=["manage.team_users"],
            is_active=True,
        )
        self.client.force_authenticate(admin)

        response = self.client.post(
            reverse("team-users-send-invite"),
            {"member_ids": [member.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.data)

    def test_edit_rejects_duplicate_email_without_partially_changing_name(self):
        member = self._member("editable@example.com", False, "Original Name")
        self._member("taken@example.com", False, "Taken Name")

        response = self.client.patch(
            reverse("team-user-detail", kwargs={"member_id": member.id}),
            {"name": "Changed Name", "email": "taken@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        member.refresh_from_db()
        self.assertEqual(member.username, "Original Name")

    @patch("account.emailsend.EmailInvitationLink")
    def test_invitation_worker_records_partial_provider_failure(self, mocked_send):
        failed_member = self._member("failed@example.com", False)
        sent_member = self._member("sent@example.com", False)
        queue_response = self.client.post(
            reverse("team-users-send-invite"),
            {"member_ids": [failed_member.id, sent_member.id]},
            format="json",
        )
        self.assertEqual(queue_response.status_code, 200, queue_response.data)
        mocked_send.side_effect = [RuntimeError("provider unavailable"), True]

        self.assertTrue(process_next_team_driver_invitation())
        self.assertTrue(process_next_team_driver_invitation())

        failed_invite = TeamMemberInvite.objects.get(team_member_object=failed_member)
        sent_invite = TeamMemberInvite.objects.get(team_member_object=sent_member)
        self.assertEqual(failed_invite.delivery_status, TeamMemberInvite.DeliveryStatus.FAILED)
        self.assertIn("provider unavailable", failed_invite.delivery_failure_detail)
        self.assertEqual(sent_invite.delivery_status, TeamMemberInvite.DeliveryStatus.SENT)
        self.assertIsNotNone(sent_invite.invite_sent_at)

    def test_download_uses_required_filename(self):
        response = self.client.get(reverse("team-users-download-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="team_users_export.csv"',
        )

