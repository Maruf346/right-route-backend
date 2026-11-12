import json
import logging
import os
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional

import requests
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.constants import PURCHASE_VERIFY_STATUS, UserSubscriptionStatus

logger = logging.getLogger(__name__)

ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
ANDROID_PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

DUMMY_PREFIXES = ("token_", "tx_", "fake_", "dummy_", "mock_")


def is_dummy_store_token(value: Optional[str]) -> bool:
    if not value:
        return True
    normalized = str(value).strip().lower()
    if not normalized or len(normalized) < 8:
        return True
    return normalized.startswith(DUMMY_PREFIXES)


def _parse_rfc3339(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except ValueError:
        return None


class GooglePlayBillingService:
    """Server-side Google Play Developer API v3 verification & acknowledgement."""

    @staticmethod
    def get_package_name(override: Optional[str] = None) -> str:
        return (override or getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "com.rightroutes.running")).strip()

    @staticmethod
    def has_credentials() -> bool:
        raw_json = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "") or ""
        file_path = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "") or ""
        if raw_json.strip():
            return True
        return bool(file_path.strip() and os.path.exists(file_path.strip()))

    @staticmethod
    def _load_credentials():
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        raw_json = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "") or ""
        file_path = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "") or ""

        if raw_json.strip():
            info = json.loads(raw_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=[ANDROID_PUBLISHER_SCOPE]
            )
        elif file_path.strip() and os.path.exists(file_path.strip()):
            creds = service_account.Credentials.from_service_account_file(
                file_path.strip(), scopes=[ANDROID_PUBLISHER_SCOPE]
            )
        else:
            raise RuntimeError("Google Play service account credentials are not configured.")

        creds.refresh(Request())
        return creds

    @classmethod
    def fetch_subscription_v2(cls, *, package_name: str, purchase_token: str) -> dict[str, Any]:
        creds = cls._load_credentials()
        url = f"{ANDROID_PUBLISHER_BASE}/{package_name}/purchases/subscriptionsv2/tokens/{purchase_token}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Google Play subscriptionsv2.get failed (%s): %s",
                resp.status_code,
                resp.text[:500],
            )
            raise ValidationError(
                {"purchase_token": f"Google Play verification failed (HTTP {resp.status_code})."}
            )
        return resp.json()

    @classmethod
    def acknowledge_subscription(
        cls,
        *,
        package_name: str,
        product_id: str,
        purchase_token: str,
        developer_payload: str = "",
    ) -> None:
        creds = cls._load_credentials()
        url = (
            f"{ANDROID_PUBLISHER_BASE}/{package_name}/purchases/subscriptions/"
            f"{product_id}/tokens/{purchase_token}:acknowledge"
        )
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
            json={"developerPayload": developer_payload[:128]},
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Google Play acknowledge failed (%s): %s",
                resp.status_code,
                resp.text[:500],
            )
            raise ValidationError(
                {"purchase_token": f"Google Play acknowledgement failed (HTTP {resp.status_code})."}
            )

    @classmethod
    def verify_purchase(
        cls,
        *,
        product_id: str,
        purchase_token: str,
        transaction_id: Optional[str] = None,
        package_name: Optional[str] = None,
        trial_days: int = 7,
        fallback_expiry: Optional[datetime] = None,
        developer_payload: str = "",
    ) -> dict[str, Any]:
        if is_dummy_store_token(purchase_token):
            raise ValidationError(
                {"purchase_token": "Invalid or placeholder Google Play purchase token."}
            )
        if transaction_id and is_dummy_store_token(transaction_id):
            raise ValidationError(
                {"transaction_id": "Invalid or placeholder transaction ID."}
            )

        resolved_package = cls.get_package_name(package_name)

        if cls.has_credentials():
            payload = cls.fetch_subscription_v2(
                package_name=resolved_package,
                purchase_token=purchase_token,
            )
            line_items = payload.get("lineItems") or []
            matched_item = next(
                (item for item in line_items if item.get("productId") == product_id),
                None,
            )
            if not matched_item:
                raise ValidationError(
                    {"product_id": "Purchased Google Play product does not match selected plan."}
                )

            state = payload.get("subscriptionState", "")
            expiry_time = _parse_rfc3339(matched_item.get("expiryTime"))
            start_time = _parse_rfc3339(payload.get("startTime")) or timezone.now()
            now = timezone.now()

            if state in ("SUBSCRIPTION_STATE_EXPIRED", "SUBSCRIPTION_STATE_PENDING"):
                raise ValidationError(
                    {"detail": f"Google Play subscription is not active ({state})."}
                )
            if state == "SUBSCRIPTION_STATE_ON_HOLD":
                raise ValidationError(
                    {"detail": "Google Play subscription is on account hold due to billing issue."}
                )
            if expiry_time and expiry_time <= now:
                raise ValidationError(
                    {"detail": "This Google Play subscription has already expired."}
                )

            offer_details = matched_item.get("offerDetails") or {}
            offer_tags = [str(t).lower() for t in (offer_details.get("offerTags") or [])]
            offer_id = str(offer_details.get("offerId") or "").lower()
            is_trial = any("trial" in tag for tag in offer_tags) or ("trial" in offer_id)

            if state == "SUBSCRIPTION_STATE_IN_GRACE_PERIOD":
                sub_status = UserSubscriptionStatus.GRACE_PERIOD
            elif is_trial:
                sub_status = UserSubscriptionStatus.TRIAL
            else:
                sub_status = UserSubscriptionStatus.ACTIVE

            auto_renew = bool((matched_item.get("autoRenewingPlan") or {}).get("autoRenewEnabled", False))
            if payload.get("acknowledgementState") != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED":
                cls.acknowledge_subscription(
                    package_name=resolved_package,
                    product_id=product_id,
                    purchase_token=purchase_token,
                    developer_payload=developer_payload,
                )

            return {
                "verification_status": PURCHASE_VERIFY_STATUS.VERIFIED,
                "verification_source": "google_play_api_v2",
                "subscription_status": sub_status,
                "purchase_time": start_time,
                "expiry_time": expiry_time or fallback_expiry or (now + timedelta(days=max(trial_days, 1))),
                "auto_renew": auto_renew,
                "order_id": payload.get("latestOrderId") or transaction_id,
                "linked_purchase_token": payload.get("linkedPurchaseToken"),
                "package_name": resolved_package,
                "raw_response": payload,
            }

        if not getattr(settings, "GOOGLE_PLAY_ALLOW_UNVERIFIED", True):
            raise ValidationError(
                {"detail": "Google Play verification service account is not configured on the server."}
            )

        now = timezone.now()
        default_expiry = (
            fallback_expiry
            if fallback_expiry and fallback_expiry > now
            else now + timedelta(days=trial_days if trial_days > 0 else 30)
        )
        logger.warning(
            "GOOGLE_PLAY_SERVICE_ACCOUNT credentials not set; accepting real Play token for %s in fallback mode.",
            product_id,
        )
        return {
            "verification_status": PURCHASE_VERIFY_STATUS.PENDING,
            "verification_source": "client_fallback_unconfigured",
            "subscription_status": UserSubscriptionStatus.TRIAL if trial_days > 0 else UserSubscriptionStatus.ACTIVE,
            "purchase_time": now,
            "expiry_time": default_expiry,
            "auto_renew": True,
            "order_id": transaction_id,
            "linked_purchase_token": None,
            "package_name": resolved_package,
            "raw_response": {"verification_source": "client_fallback_unconfigured"},
        }
