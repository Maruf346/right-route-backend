import base64
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from account.models import User
from core.constants import PlanType, UserSubscriptionStatus, UserType
from subscription.models import PurchaseInfo, SubscriptionPlan, UserSubscription


class GooglePlaySubscriptionFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="driver@example.com",
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="OtherPass123!",
            user_type=UserType.MAIN_USER,
        )
        self.client.force_authenticate(user=self.user)

    def test_seeded_play_console_plans_present_with_seven_day_trial(self):
        response = self.client.get("/api/v1/subscription-plans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        plans = response.data if isinstance(response.data, list) else response.data.get("results", response.data)
        product_ids = {p["product_id"] for p in plans}
        expected = {
            "rr_individual_annual",
            "rr_individual_monthly",
            "rr_team_5_monthly",
            "rr_team_10_monthly",
            "rr_team_25_monthly",
            "rr_team_50_monthly",
            "rr_team_100_monthly",
        }
        self.assertTrue(expected.issubset(product_ids))
        for plan in plans:
            if plan["product_id"] in expected:
                self.assertEqual(plan["trial_days"], 7)

    def test_rejects_dummy_client_tokens(self):
        plan = SubscriptionPlan.objects.get(product_id="rr_individual_monthly")
        init_resp = self.client.post("/api/v1/subscription/purchase/", {"plan_id": plan.id}, format="json")
        self.assertEqual(init_resp.status_code, status.HTTP_201_CREATED)
        sub_uuid = init_resp.data["data"]["uuid"]

        verify_resp = self.client.post(
            "/api/v1/subscription/purchase-verify/",
            {
                "platform": "android",
                "subscription_plan_uuid": sub_uuid,
                "product_id": plan.product_id,
                "transaction_id": "tx_1234567890",
                "purchase_token": "token_1234567890",
            },
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(GOOGLE_PLAY_SERVICE_ACCOUNT_JSON='{"type":"service_account"}')
    @patch("subscription.services.google_play.GooglePlayBillingService.acknowledge_subscription")
    @patch("subscription.services.google_play.GooglePlayBillingService.fetch_subscription_v2")
    def test_google_play_v2_verification_and_team_upgrade(self, mock_fetch, mock_ack):
        future_expiry = (timezone.now() + timedelta(days=7)).isoformat().replace("+00:00", "Z")
        start_time = timezone.now().isoformat().replace("+00:00", "Z")

        mock_fetch.return_value = {
            "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
            "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
            "startTime": start_time,
            "latestOrderId": "GPA.3311-2222-3333-44445",
            "lineItems": [
                {
                    "productId": "rr_individual_monthly",
                    "expiryTime": future_expiry,
                    "autoRenewingPlan": {"autoRenewEnabled": True},
                    "offerDetails": {"offerId": "free-trial-7d", "offerTags": ["free-trial"]},
                }
            ],
        }

        ind_plan = SubscriptionPlan.objects.get(product_id="rr_individual_monthly")
        p1 = self.client.post("/api/v1/subscription/purchase/", {"plan_id": ind_plan.id}, format="json")
        self.assertEqual(p1.status_code, status.HTTP_201_CREATED)

        v1 = self.client.post(
            "/api/v1/subscription/purchase-verify/",
            {
                "platform": "android",
                "subscription_plan_uuid": p1.data["data"]["uuid"],
                "product_id": ind_plan.product_id,
                "transaction_id": "GPA.3311-2222-3333-44445",
                "purchase_token": "real_play_purchase_token_individual_abcdef12345",
                "package_name": "com.rightroutes.running",
            },
            format="json",
        )
        self.assertEqual(v1.status_code, status.HTTP_200_OK)
        self.assertEqual(v1.data["subscription_status"], "trial")
        mock_ack.assert_called_once()

        # Now upgrade to Team 25 Drivers
        team_plan = SubscriptionPlan.objects.get(product_id="rr_team_25_monthly")
        mock_fetch.return_value = {
            "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
            "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
            "startTime": start_time,
            "latestOrderId": "GPA.5555-6666-7777-88888",
            "lineItems": [
                {
                    "productId": "rr_team_25_monthly",
                    "expiryTime": future_expiry,
                    "autoRenewingPlan": {"autoRenewEnabled": True},
                    "offerDetails": {"offerId": "free-trial-7d", "offerTags": ["trial"]},
                }
            ],
        }

        p2 = self.client.post("/api/v1/subscription/purchase/", {"plan_id": team_plan.id}, format="json")
        self.assertEqual(p2.status_code, status.HTTP_201_CREATED)

        v2 = self.client.post(
            "/api/v1/subscription/purchase-verify/",
            {
                "platform": "android",
                "subscription_plan_uuid": p2.data["data"]["uuid"],
                "product_id": team_plan.product_id,
                "transaction_id": "GPA.5555-6666-7777-88888",
                "purchase_token": "real_play_purchase_token_team25_xyz987654",
                "package_name": "com.rightroutes.running",
            },
            format="json",
        )
        self.assertEqual(v2.status_code, status.HTTP_200_OK)
        self.user.owned_team.refresh_from_db()
        self.assertEqual(self.user.owned_team.max_members, 25)

        old_sub = UserSubscription.objects.get(uuid=p1.data["data"]["uuid"])
        self.assertEqual(old_sub.status, UserSubscriptionStatus.CANCELLED)

        # Other user cannot hijack the same purchase_token
        self.client.force_authenticate(user=self.other_user)
        p_other = self.client.post("/api/v1/subscription/purchase/", {"plan_id": team_plan.id}, format="json")
        v_other = self.client.post(
            "/api/v1/subscription/purchase-verify/",
            {
                "platform": "android",
                "subscription_plan_uuid": p_other.data["data"]["uuid"],
                "product_id": team_plan.product_id,
                "transaction_id": "GPA.9999-0000-1111-22222",
                "purchase_token": "real_play_purchase_token_team25_xyz987654",
            },
            format="json",
        )
        self.assertEqual(v_other.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restore_and_rtdn_webhook(self):
        team_plan = SubscriptionPlan.objects.get(product_id="rr_team_10_monthly")
        restore_resp = self.client.post(
            "/api/v1/subscription/restore/",
            {
                "platform": "android",
                "purchases": [
                    {
                        "product_id": team_plan.product_id,
                        "transaction_id": "GPA.7777-8888-9999-00001",
                        "purchase_token": "restorable_play_token_team10_1234567890",
                        "package_name": "com.rightroutes.running",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(restore_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(restore_resp.data["restored"])
        self.assertEqual(restore_resp.data["data"]["plan_product_id"], "rr_team_10_monthly")
        self.user.owned_team.refresh_from_db()
        self.assertEqual(self.user.owned_team.max_members, 10)

        # Simulate RTDN EXPIRED notification
        notif_json = json.dumps({
            "packageName": "com.rightroutes.running",
            "subscriptionNotification": {
                "notificationType": 13,
                "purchaseToken": "restorable_play_token_team10_1234567890",
                "subscriptionId": "rr_team_10_monthly",
            },
        })
        b64_payload = base64.b64encode(notif_json.encode("utf-8")).decode("utf-8")
        rtdn_resp = self.client.post(
            "/api/v1/subscription/google-play-rtdn/",
            {"message": {"data": b64_payload}},
            format="json",
        )
        self.assertEqual(rtdn_resp.status_code, status.HTTP_200_OK)
        sub = UserSubscription.objects.get(uuid=restore_resp.data["data"]["uuid"])
        self.assertEqual(sub.status, UserSubscriptionStatus.EXPIRED)
