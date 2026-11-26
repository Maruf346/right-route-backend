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


@override_settings(SECURE_SSL_REDIRECT=False)
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

        plans = response.data if isinstance(response.data, list) else (response.data.get("data") or response.data.get("results") or [])
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


@override_settings(
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="service@getrightroute.app",
    EMAIL_HOST_PASSWORD="test-password",
    DEFAULT_FROM_EMAIL="RightRoute <service@getrightroute.app>",
    STRIPE_SECRET_KEY="sk_test_dummy_replace_with_real_key",
)
class FleetCouponAndEmailTests(TestCase):
    def setUp(self):
        from django.core import mail
        mail.outbox.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="superadmin@getrightroute.app",
            password="AdminPass123!",
            user_type=UserType.ADMIN,
            is_staff=True,
            is_superuser=True,
            is_email_verified=True,
        )
        self.client.force_authenticate(user=self.admin)

    def test_single_subscriber_welcome_email_sent_once(self):
        from django.core import mail

        driver = User.objects.create_user(
            email="single_buyer@example.com",
            password="DriverPass123!",
            user_type=UserType.MAIN_USER,
        )
        driver_client = APIClient()
        driver_client.force_authenticate(user=driver)

        plan = SubscriptionPlan.objects.get(product_id="rr_individual_monthly")
        p1 = driver_client.post("/api/v1/subscription/purchase/", {"plan_id": plan.id}, format="json")
        self.assertEqual(p1.status_code, status.HTTP_201_CREATED)

        with patch("subscription.services.google_play.GooglePlayBillingService.verify_purchase") as mock_verify:
            mock_verify.return_value = {
                "verification_status": "verified",
                "subscription_status": UserSubscriptionStatus.TRIAL,
                "purchase_time": timezone.now(),
                "expiry_time": timezone.now() + timedelta(days=7),
                "auto_renew": True,
                "order_id": "GPA.SINGLE.001",
                "package_name": "com.rightroutes.running",
                "raw_response": {},
            }
            v1 = driver_client.post(
                "/api/v1/subscription/purchase-verify/",
                {
                    "platform": "android",
                    "subscription_plan_uuid": p1.data["data"]["uuid"],
                    "product_id": plan.product_id,
                    "transaction_id": "GPA.SINGLE.001",
                    "purchase_token": "single_play_token_001",
                },
                format="json",
            )
        self.assertEqual(v1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Welcome to RightRoute. Important information enclosed")
        self.assertIn("Hello,", msg.body)
        self.assertIn("https://getrightroute.app/Single-Driver-User-Guide.pdf", msg.body)
        self.assertIn("https://youtu.be/YqIv0VveXI4", msg.body)
        self.assertIn("https://youtu.be/7IwaA_PQws4", msg.body)

        # Re-verifying same subscription should not send duplicate welcome email
        with patch("subscription.services.google_play.GooglePlayBillingService.verify_purchase") as mock_verify:
            mock_verify.return_value = {
                "verification_status": "verified",
                "subscription_status": UserSubscriptionStatus.ACTIVE,
                "purchase_time": timezone.now(),
                "expiry_time": timezone.now() + timedelta(days=30),
                "auto_renew": True,
                "order_id": "GPA.SINGLE.001",
                "package_name": "com.rightroutes.running",
                "raw_response": {},
            }
            v2 = driver_client.post(
                "/api/v1/subscription/purchase-verify/",
                {
                    "platform": "android",
                    "subscription_plan_uuid": p1.data["data"]["uuid"],
                    "product_id": plan.product_id,
                    "transaction_id": "GPA.SINGLE.001",
                    "purchase_token": "single_play_token_001",
                },
                format="json",
            )
        self.assertEqual(v2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_fleet_account_crud_welcome_email_and_finance_integration(self):
        from django.core import mail
        from subscription.models import FleetAccount

        create_resp = self.client.post(
            "/api/v1/admin/subscribers/fleets/",
            {
                "full_name": "Brandon Keller",
                "company_name": "Keller Transport",
                "email": "brandon@kellertransport.com",
                "phone": "555-012-6789",
                "password": "FleetStrongPass99!",
                "sign_up_date": "2026-11-26",
                "next_payment_date": "2026-12-26",
                "driver_allowance": 250,
                "price": "1850.00",
                "billing_type": "MONTHLY",
                "discount_period": "3 months",
                "discount_amount": "$150.00",
                "state": "Texas",
                "platform": "Stripe",
                "notes": "Enterprise heavy-haul fleet.",
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        fleet_data = create_resp.data["data"]
        fleet_id = fleet_data["id"]
        self.assertEqual(fleet_data["driver_allowance"], 250)
        self.assertEqual(fleet_data["stripe_sync_status"], "DUMMY_MODE")

        # Excluded from normal Manage Teams list
        teams_resp = self.client.get("/api/v1/admin/subscribers/teams/")
        self.assertEqual(teams_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(teams_resp.data["count"], 0)

        # Send Welcome Email button
        email_resp = self.client.post(
            f"/api/v1/admin/subscribers/fleets/{fleet_id}/send-welcome-email/",
            {"password": "FleetStrongPass99!"},
            format="json",
        )
        self.assertEqual(email_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Payment confirmation, your login credentials")
        self.assertIn("Hello Brandon,", msg.body)
        self.assertIn("brandon@kellertransport.com", msg.body)
        self.assertIn("FleetStrongPass99!", msg.body)
        self.assertIn("https://team.getrightroute.app", msg.body)
        self.assertIn("https://youtu.be/A_TR1diPniA", msg.body)
        self.assertIn("https://youtu.be/PCb9BEpqdF8", msg.body)
        self.assertIn("Team-Fleet-User-Guide.pdf", {a[0] for a in msg.attachments})

        # Fleet payments finance endpoint reflects real FleetAccount
        fin_resp = self.client.get(
            "/api/v1/finance/fleet-payments/summary/?period=month&year=2026&month=12"
        )
        self.assertEqual(fin_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(float(fin_resp.data["total_amount"]), 1850.0)

        # Lock & Unlock
        lock_resp = self.client.post(f"/api/v1/admin/subscribers/fleets/{fleet_id}/lock/")
        self.assertEqual(lock_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(lock_resp.data["data"]["locked"])

        unlock_resp = self.client.post(f"/api/v1/admin/subscribers/fleets/{fleet_id}/unlock/")
        self.assertEqual(unlock_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(unlock_resp.data["data"]["locked"])

        self.assertEqual(FleetAccount.objects.count(), 1)

    def test_coupon_crud_and_web_checkout_discount_flow(self):
        from subscription.models import DiscountCoupon

        coupon_resp = self.client.post(
            "/api/v1/admin/coupons/",
            {
                "code": "save20web",
                "description": "20% off for web Team plans",
                "discount_type": "PERCENTAGE",
                "discount_value": "20.00",
                "duration": "REPEATING",
                "duration_in_months": 3,
                "applicable_plan_type": "TEAM",
                "max_redemptions": 10,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(coupon_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(coupon_resp.data["data"]["code"], "SAVE20WEB")

        # Unauthenticated buyer on web checkout validates coupon against Team 10 plan
        web_client = APIClient()
        team_plan = SubscriptionPlan.objects.get(product_id="rr_team_10_monthly")
        val_resp = web_client.post(
            "/api/v1/subscription/coupons/validate/",
            {"code": "SAVE20WEB", "plan_id": team_plan.id},
            format="json",
        )
        self.assertEqual(val_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(val_resp.data["data"]["discount_period"], "3 months")
        self.assertNotEqual(val_resp.data["data"]["final_price"], val_resp.data["data"]["original_price"])

        # Reject coupon on Individual plan because scope is TEAM
        ind_plan = SubscriptionPlan.objects.get(product_id="rr_individual_monthly")
        bad_val = web_client.post(
            "/api/v1/subscription/coupons/validate/",
            {"code": "SAVE20WEB", "plan_id": ind_plan.id},
            format="json",
        )
        self.assertEqual(bad_val.status_code, status.HTTP_400_BAD_REQUEST)

        # Create dummy web checkout session + confirm
        co_resp = web_client.post(
            "/api/v1/subscription/web-checkout/",
            {
                "plan_id": team_plan.id,
                "coupon_code": "SAVE20WEB",
                "email": "webbuyer@company.com",
                "password": "WebBuyerPass123!",
            },
            format="json",
        )
        self.assertEqual(co_resp.status_code, status.HTTP_200_OK)
        session_id = co_resp.data["data"]["session_id"]

        confirm_resp = web_client.post(
            "/api/v1/subscription/web-checkout/confirm-test/",
            {"session_id": session_id},
            format="json",
        )
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_resp.data["data"]["status"], UserSubscriptionStatus.ACTIVE)

        coupon = DiscountCoupon.objects.get(code="SAVE20WEB")
        self.assertEqual(coupon.times_redeemed, 1)
        buyer = User.objects.get(email="webbuyer@company.com")
        self.assertEqual(buyer.owned_team.max_members, 10)

    @override_settings(
        STRIPE_SECRET_KEY="rk_live_" + "unit_test_key",
        STRIPE_WEBHOOK_SECRET="whsec_" + "unit_test_secret",
    )
    @patch("subscription.services.stripe_service.get_stripe_client")
    def test_restricted_rk_live_key_and_endive_webhook_invoice_format(self, mock_get_client):
        from datetime import date
        from subscription.models import DiscountCoupon, FleetAccount
        from subscription.services.stripe_service import is_stripe_configured, process_stripe_webhook_event

        self.assertTrue(is_stripe_configured())

        mock_client = MagicMock()
        mock_client.Coupon.create.return_value = MagicMock(id="coup_123")
        mock_client.PromotionCode.create.return_value = MagicMock(id="promo_123")
        mock_client.Customer.list.return_value = MagicMock(data=[])
        mock_client.Customer.create.return_value = MagicMock(id="cus_fleet_1")
        mock_client.Product.create.return_value = MagicMock(id="prod_fleet_1")
        mock_client.Price.create.return_value = MagicMock(id="price_fleet_1")
        mock_client.Subscription.create.return_value = MagicMock(id="sub_fleet_live_1", latest_invoice=None)
        mock_get_client.return_value = mock_client

        # Creating & toggling coupon uses Stripe 2026-11-18 promotion dict & modifies active flag
        coupon_resp = self.client.post(
            "/api/v1/admin/coupons/",
            {
                "code": "LIVE25",
                "description": "25% off",
                "discount_type": "PERCENTAGE",
                "discount_value": "25.00",
                "duration": "ONCE",
                "applicable_plan_type": "ALL",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(coupon_resp.status_code, status.HTTP_201_CREATED)
        mock_client.PromotionCode.create.assert_called_once_with(
            promotion={"type": "coupon", "coupon": "coup_123"},
            code="LIVE25",
            active=True,
        )
        coupon = DiscountCoupon.objects.get(code="LIVE25")
        toggle_resp = self.client.post(f"/api/v1/admin/coupons/{coupon.id}/toggle-active/")
        self.assertEqual(toggle_resp.status_code, status.HTTP_200_OK)
        mock_client.PromotionCode.modify.assert_called_once_with("promo_123", active=False)

        # Create fleet account (will sync against mocked Stripe rk_live client)
        fleet_resp = self.client.post(
            "/api/v1/admin/subscribers/fleets/",
            {
                "full_name": "Fleet Tester",
                "company_name": "Test Haulers",
                "email": "fleettst@example.com",
                "password": "FleetStrongPass99!",
                "sign_up_date": "2026-11-26",
                "next_payment_date": "2026-12-26",
                "driver_allowance": 120,
                "price": "1200.00",
                "billing_type": "MONTHLY",
            },
            format="json",
        )
        self.assertEqual(fleet_resp.status_code, status.HTTP_201_CREATED)
        fleet = FleetAccount.objects.get(user__email="fleettst@example.com")
        self.assertEqual(fleet.stripe_sync_status, "SYNCED")
        self.assertEqual(fleet.stripe_subscription_id, "sub_fleet_live_1")

        # Simulate Stripe 2026-11-18.endive invoice.paid payload (subscription nested under parent)
        mock_client.Webhook.construct_event.return_value = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_live_001",
                    "hosted_invoice_url": "https://invoice.stripe.com/i/acct/test",
                    "parent": {
                        "type": "subscription_details",
                        "subscription_details": {"subscription": "sub_fleet_live_1"},
                    },
                }
            },
        }
        process_stripe_webhook_event(b"{}", "sig_header")
        fleet.refresh_from_db()
        self.assertEqual(fleet.next_payment_date, date(2027, 1, 25))
        self.assertEqual(fleet.stripe_latest_invoice_id, "in_live_001")

        # Duplicate webhook retry for same invoice must not advance date twice
        process_stripe_webhook_event(b"{}", "sig_header")
        fleet.refresh_from_db()
        self.assertEqual(fleet.next_payment_date, date(2027, 1, 25))

        # Simulate invoice.payment_failed nested under parent -> marks FAILED (not mistaking in_ id)
        mock_client.Webhook.construct_event.return_value = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_live_002",
                    "parent": {
                        "type": "subscription_details",
                        "subscription_details": {"subscription": "sub_fleet_live_1"},
                    },
                }
            },
        }
        process_stripe_webhook_event(b"{}", "sig_header")
        fleet.refresh_from_db()
        self.assertEqual(fleet.status, UserSubscriptionStatus.FAILED)
