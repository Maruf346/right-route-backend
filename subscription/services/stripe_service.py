import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
import uuid

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from account.emailsend import EmailSingleSubscriberWelcome
from account.models import Team, User
from core.constants import (
    BillingType,
    CouponDiscountType,
    CouponDurationType,
    PaymentStatus,
    PlanType,
    PURCHASE_PLATFORM,
    PURCHASE_VERIFY_STATUS,
    UserSubscriptionStatus,
)
from subscription.models import (
    CouponRedemption,
    DiscountCoupon,
    FleetAccount,
    PurchaseInfo,
    SubscriptionPlan,
    UserSubscription,
)

logger = logging.getLogger(__name__)


def is_stripe_configured():
    """Return True when a non-placeholder Stripe secret key is configured."""
    key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not key:
        return False
    lowered = key.lower()
    if "dummy" in lowered or "replace" in lowered or "example" in lowered:
        return False
    return key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_"))


def get_stripe_client():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def get_or_create_fleet_plan():
    """Return the internal SubscriptionPlan record backing custom B2B Fleet accounts."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        product_id="rr_fleet_custom",
        defaults={
            "name": "Fleet Custom",
            "plan_type": PlanType.TEAM,
            "billing_type": BillingType.MONTHLY,
            "team_limit": 0,
            "price": Decimal("0.00"),
            "currency": "USD",
            "trial_days": 0,
            "is_active": False,
        },
    )
    return plan


def sync_fleet_to_stripe(fleet_account: FleetAccount):
    """
    Create or update Stripe Customer & Subscription (automatic invoice collection)
    for a FleetAccount. When dummy Stripe keys are configured, records DUMMY_MODE
    without breaking admin account creation.
    """
    if not is_stripe_configured():
        fleet_account.stripe_sync_status = "DUMMY_MODE"
        fleet_account.stripe_sync_error = (
            "Dummy Stripe API key active. Replace STRIPE_SECRET_KEY to sync with live/test Stripe."
        )
        fleet_account.save(update_fields=["stripe_sync_status", "stripe_sync_error", "updated_at"])
        return fleet_account

    client = get_stripe_client()
    try:
        customer_payload = {
            "email": fleet_account.user.email,
            "name": fleet_account.company_name or fleet_account.full_name,
            "metadata": {
                "fleet_account_id": str(fleet_account.id),
                "team_id": str(fleet_account.team_id),
                "driver_allowance": str(fleet_account.driver_allowance),
            },
        }
        if fleet_account.phone:
            customer_payload["phone"] = fleet_account.phone
        if fleet_account.stripe_customer_id:
            customer = client.Customer.modify(fleet_account.stripe_customer_id, **customer_payload)
        else:
            existing = client.Customer.list(email=fleet_account.user.email, limit=1)
            if existing.data:
                customer = client.Customer.modify(existing.data[0].id, **customer_payload)
            else:
                customer = client.Customer.create(**customer_payload)
        fleet_account.stripe_customer_id = customer.id

        # Calculate net recurring price if fixed/percentage discount string was supplied
        unit_amount_cents = max(int((fleet_account.price or Decimal("0.00")) * 100), 0)
        interval = "year" if fleet_account.billing_type == BillingType.YEARLY else "month"
        days_until_due = 14 if fleet_account.billing_type == BillingType.YEARLY else 7

        if unit_amount_cents > 0 and not fleet_account.stripe_subscription_id:
            product = client.Product.create(
                name=f"RightRoute Fleet - {fleet_account.company_name or fleet_account.full_name}",
                metadata={"fleet_account_id": str(fleet_account.id)},
            )
            price_obj = client.Price.create(
                product=product.id,
                unit_amount=unit_amount_cents,
                currency="usd",
                recurring={"interval": interval},
            )
            sub_kwargs = {
                "customer": customer.id,
                "items": [{"price": price_obj.id}],
                "collection_method": "send_invoice",
                "days_until_due": days_until_due,
                "metadata": {
                    "fleet_account_id": str(fleet_account.id),
                    "team_id": str(fleet_account.team_id),
                    "billing_type": fleet_account.billing_type,
                },
            }
            if fleet_account.next_payment_date:
                # Send the upcoming recurring invoice before next_payment_date begins
                anchor_date = fleet_account.next_payment_date
                lead_days = 14 if fleet_account.billing_type == BillingType.YEARLY else 7
                send_date = anchor_date - timedelta(days=lead_days)
                now_dt = timezone.now()
                target_dt = timezone.make_aware(datetime.combine(send_date, time(hour=9, minute=0)))
                if target_dt > now_dt + timedelta(minutes=10):
                    sub_kwargs["trial_end"] = int(target_dt.timestamp())

            stripe_sub = client.Subscription.create(**sub_kwargs)
            fleet_account.stripe_subscription_id = stripe_sub.id
            if getattr(stripe_sub, "latest_invoice", None):
                latest_inv_id = getattr(stripe_sub.latest_invoice, "id", None) or str(stripe_sub.latest_invoice)
                fleet_account.stripe_latest_invoice_id = latest_inv_id
                if hasattr(stripe_sub.latest_invoice, "hosted_invoice_url"):
                    fleet_account.stripe_invoice_url = stripe_sub.latest_invoice.hosted_invoice_url or ""
                else:
                    try:
                        inv = client.Invoice.retrieve(latest_inv_id)
                        fleet_account.stripe_invoice_url = inv.hosted_invoice_url or ""
                    except Exception:
                        pass

            if fleet_account.subscription:
                fleet_account.subscription.stripe_subscription_id = stripe_sub.id
                fleet_account.subscription.save(update_fields=["stripe_subscription_id", "updated_at"])

        fleet_account.stripe_sync_status = "SYNCED"
        fleet_account.stripe_sync_error = ""
        fleet_account.save(update_fields=[
            "stripe_customer_id",
            "stripe_subscription_id",
            "stripe_latest_invoice_id",
            "stripe_invoice_url",
            "stripe_sync_status",
            "stripe_sync_error",
            "updated_at",
        ])
    except Exception as exc:
        logger.exception("Stripe sync failed for FleetAccount %s", fleet_account.id)
        fleet_account.stripe_sync_status = "ERROR"
        fleet_account.stripe_sync_error = str(exc)[:1000]
        fleet_account.save(update_fields=["stripe_sync_status", "stripe_sync_error", "updated_at"])
    return fleet_account


def sync_coupon_to_stripe(coupon: DiscountCoupon):
    """Sync a DiscountCoupon record to Stripe Coupon + PromotionCode when live Stripe keys exist."""
    if not is_stripe_configured():
        return coupon

    client = get_stripe_client()
    try:
        if not coupon.stripe_coupon_id:
            params = {
                "name": coupon.code,
                "duration": coupon.duration.lower(),
                "metadata": {"coupon_id": str(coupon.id), "scope": coupon.applicable_plan_type},
            }
            if coupon.discount_type == CouponDiscountType.PERCENTAGE:
                params["percent_off"] = float(coupon.discount_value)
            else:
                params["amount_off"] = max(int(coupon.discount_value * 100), 1)
                params["currency"] = "usd"

            if coupon.duration == CouponDurationType.REPEATING and coupon.duration_in_months:
                params["duration_in_months"] = int(coupon.duration_in_months)

            if coupon.max_redemptions:
                params["max_redemptions"] = int(coupon.max_redemptions)

            if coupon.valid_until:
                params["redeem_by"] = int(coupon.valid_until.timestamp())

            stripe_coupon = client.Coupon.create(**params)
            coupon.stripe_coupon_id = stripe_coupon.id

        if not coupon.stripe_promotion_code_id and coupon.stripe_coupon_id:
            promo = client.PromotionCode.create(
                promotion={"type": "coupon", "coupon": coupon.stripe_coupon_id},
                code=coupon.code,
                active=coupon.is_active,
            )
            coupon.stripe_promotion_code_id = promo.id
        elif coupon.stripe_promotion_code_id:
            client.PromotionCode.modify(
                coupon.stripe_promotion_code_id,
                active=coupon.is_active,
            )

        coupon.save(update_fields=["stripe_coupon_id", "stripe_promotion_code_id", "updated_at"])
    except Exception as exc:
        logger.warning("Unable to sync coupon %s to Stripe: %s", coupon.code, exc)
    return coupon


@transaction.atomic
def activate_web_subscription_from_checkout(
    *,
    user: User,
    plan: SubscriptionPlan,
    coupon: DiscountCoupon = None,
    redemption: CouponRedemption = None,
    stripe_session_id: str = "",
    stripe_subscription_id: str = "",
    amount_paid: Decimal = None,
):
    """Activate a web-purchased Individual/Team subscription and record coupon redemption."""
    now = timezone.now()
    duration_days = 365 if plan.billing_type == BillingType.YEARLY else 30
    expires_at = now + timedelta(days=duration_days)

    # Supersede existing active subscriptions
    UserSubscription.objects.filter(
        user=user,
        status__in=[
            UserSubscriptionStatus.ACTIVE,
            UserSubscriptionStatus.TRIAL,
            UserSubscriptionStatus.GRACE_PERIOD,
        ],
    ).update(
        status=UserSubscriptionStatus.CANCELLED,
        cancelled_at=now,
        auto_renew=False,
    )

    team = None
    if plan.plan_type == PlanType.TEAM:
        team = getattr(user, "owned_team", None)
        if not team:
            prefix = (user.email or f"user-{user.id}").split("@")[0]
            team, _ = Team.objects.get_or_create(
                owner=user,
                defaults={"name": f"{prefix}'s Team", "max_members": plan.team_limit or 0},
            )
        if plan.team_limit:
            team.max_members = plan.team_limit
            team.is_active = True
            team.save(update_fields=["max_members", "is_active", "updated_at"])

    discount_period = coupon.get_discount_period_label() if coupon else "0"
    discount_amount_str = coupon.get_discount_amount_label() if coupon else "0"
    tx_id = stripe_subscription_id or stripe_session_id or f"web_{uuid.uuid4().hex[:16]}"

    subscription = UserSubscription.objects.create(
        user=user,
        team=team,
        plan=plan,
        status=UserSubscriptionStatus.ACTIVE,
        starts_at=now,
        last_renew_at=now,
        expires_at=expires_at,
        auto_renew=True,
        payment_status=PaymentStatus.PAID,
        original_transaction_id=tx_id,
        latest_transaction_id=tx_id,
        stripe_subscription_id=stripe_subscription_id or None,
        discount_period=discount_period,
        discount_amount=discount_amount_str,
    )

    PurchaseInfo.objects.update_or_create(
        transaction_id=tx_id,
        defaults={
            "user": user,
            "subscription": subscription,
            "platform": PURCHASE_PLATFORM.WEB,
            "product_id": plan.product_id or f"web_plan_{plan.id}",
            "original_transaction_id": tx_id,
            "amount": amount_paid if amount_paid is not None else plan.price,
            "currency": plan.currency or "USD",
            "purchase_time": now,
            "expiry_time": expires_at,
            "auto_renew": True,
            "verification_status": PURCHASE_VERIFY_STATUS.VERIFIED,
            "raw_response": {"source": "web_checkout", "stripe_session_id": stripe_session_id},
        },
    )

    if redemption:
        redemption.subscription = subscription
        redemption.status = CouponRedemption.Status.COMPLETED
        redemption.save(update_fields=["subscription", "status", "updated_at"])

    if coupon:
        DiscountCoupon.objects.filter(pk=coupon.pk).update(times_redeemed=coupon.times_redeemed + 1)

    if plan.plan_type == PlanType.INDIVIDUAL:
        try:
            EmailSingleSubscriberWelcome(user)
            subscription.welcome_email_sent_at = timezone.now()
            subscription.save(update_fields=["welcome_email_sent_at", "updated_at"])
        except Exception as exc:
            logger.warning("Failed sending single welcome email to %s: %s", user.email, exc)

    return subscription


def create_web_checkout_session(
    *,
    user: User,
    plan: SubscriptionPlan,
    coupon: DiscountCoupon = None,
    success_url: str = "",
    cancel_url: str = "",
):
    """Create a Stripe Checkout session (or dummy fallback session) for web plan purchase."""
    base_price = Decimal(str(plan.price))
    discount_amount = Decimal("0.00")
    final_price = base_price
    if coupon:
        discount_amount, final_price = coupon.compute_discount(base_price)

    redemption = None
    if coupon:
        redemption = CouponRedemption.objects.create(
            coupon=coupon,
            user=user,
            plan=plan,
            original_price=base_price,
            discount_amount=discount_amount,
            final_price=final_price,
            status=CouponRedemption.Status.PENDING,
        )

    team_url = getattr(settings, "TEAM_DASHBOARD_URL", "https://team.getrightroute.app").rstrip("/")
    resolved_success = success_url or f"{team_url}/checkout?status=success&session_id={{CHECKOUT_SESSION_ID}}"
    resolved_cancel = cancel_url or f"{team_url}/checkout?status=cancelled"

    if not is_stripe_configured():
        dummy_session_id = f"cs_dummy_{uuid.uuid4().hex[:20]}"
        if redemption:
            redemption.stripe_checkout_session_id = dummy_session_id
            redemption.save(update_fields=["stripe_checkout_session_id", "updated_at"])
        return {
            "mode": "dummy",
            "session_id": dummy_session_id,
            "checkout_url": None,
            "redemption_id": redemption.id if redemption else None,
            "original_price": base_price,
            "discount_amount": discount_amount,
            "final_price": final_price,
        }

    client = get_stripe_client()
    customer_list = client.Customer.list(email=user.email, limit=1)
    if customer_list.data:
        customer_id = customer_list.data[0].id
    else:
        customer = client.Customer.create(email=user.email, metadata={"user_id": str(user.id)})
        customer_id = customer.id

    if coupon and not coupon.stripe_coupon_id:
        sync_coupon_to_stripe(coupon)

    interval = "year" if plan.billing_type == BillingType.YEARLY else "month"
    session_kwargs = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [
            {
                "price_data": {
                    "currency": (plan.currency or "USD").lower(),
                    "product_data": {"name": f"RightRoute - {plan.name}"},
                    "unit_amount": max(int(base_price * 100), 50),
                    "recurring": {"interval": interval},
                },
                "quantity": 1,
            }
        ],
        "success_url": resolved_success,
        "cancel_url": resolved_cancel,
        "metadata": {
            "user_id": str(user.id),
            "plan_id": str(plan.id),
            "coupon_id": str(coupon.id) if coupon else "",
            "redemption_id": str(redemption.id) if redemption else "",
        },
    }
    if coupon and coupon.stripe_coupon_id:
        session_kwargs["discounts"] = [{"coupon": coupon.stripe_coupon_id}]

    session = client.checkout.Session.create(**session_kwargs)
    if redemption:
        redemption.stripe_checkout_session_id = session.id
        redemption.save(update_fields=["stripe_checkout_session_id", "updated_at"])

    return {
        "mode": "stripe",
        "session_id": session.id,
        "checkout_url": session.url,
        "redemption_id": redemption.id if redemption else None,
        "original_price": base_price,
        "discount_amount": discount_amount,
        "final_price": final_price,
    }


def _extract_invoice_subscription_id(data_obj: dict) -> str:
    """
    Extract subscription ID from Stripe Invoice webhook payloads across API versions.
    In Stripe API >= 2025-03-31 / 2026-11-18.endive, subscription moves from top-level
    `subscription` into `parent.subscription_details.subscription`.
    """
    direct = data_obj.get("subscription")
    if isinstance(direct, dict):
        direct = direct.get("id")
    if direct:
        return str(direct)

    parent = data_obj.get("parent") or {}
    sub_details = parent.get("subscription_details") or {}
    sub_ref = sub_details.get("subscription")
    if isinstance(sub_ref, dict):
        sub_ref = sub_ref.get("id")
    if sub_ref:
        return str(sub_ref)

    lines = (data_obj.get("lines") or {}).get("data") or []
    for line in lines:
        line_sub = line.get("subscription")
        if isinstance(line_sub, dict):
            line_sub = line_sub.get("id")
        if line_sub:
            return str(line_sub)
        line_sub_details = (line.get("parent") or {}).get("subscription_item_details") or {}
        if line_sub_details.get("subscription"):
            return str(line_sub_details["subscription"])
    return ""


def process_stripe_webhook_event(payload_bytes: bytes, sig_header: str):
    """Verify and process incoming Stripe webhook events."""
    if not is_stripe_configured():
        raise ValueError("Stripe is not configured with live/test keys.")

    client = get_stripe_client()
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    event = client.Webhook.construct_event(payload_bytes, sig_header, webhook_secret)
    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data_obj.get("metadata") or {}
        user_id = metadata.get("user_id")
        plan_id = metadata.get("plan_id")
        coupon_id = metadata.get("coupon_id")
        redemption_id = metadata.get("redemption_id")

        if user_id and plan_id:
            user = User.objects.filter(id=user_id).first()
            plan = SubscriptionPlan.objects.filter(id=plan_id).first()
            coupon = DiscountCoupon.objects.filter(id=coupon_id).first() if coupon_id else None
            redemption = CouponRedemption.objects.filter(id=redemption_id).first() if redemption_id else None
            if user and plan:
                amount_total = data_obj.get("amount_total")
                paid_dec = (Decimal(amount_total) / Decimal("100")) if amount_total is not None else None
                activate_web_subscription_from_checkout(
                    user=user,
                    plan=plan,
                    coupon=coupon,
                    redemption=redemption,
                    stripe_session_id=data_obj.get("id", ""),
                    stripe_subscription_id=data_obj.get("subscription") or "",
                    amount_paid=paid_dec,
                )

    elif event_type == "invoice.paid":
        stripe_sub_id = _extract_invoice_subscription_id(data_obj)
        invoice_id = data_obj.get("id", "")
        if stripe_sub_id:
            fleet = FleetAccount.objects.filter(stripe_subscription_id=stripe_sub_id).first()
            if fleet:
                already_recorded = invoice_id and fleet.stripe_latest_invoice_id == invoice_id
                delta = timedelta(days=365) if fleet.billing_type == BillingType.YEARLY else timedelta(days=30)
                if not already_recorded:
                    base_date = fleet.next_payment_date or timezone.localdate()
                    fleet.next_payment_date = base_date + delta
                fleet.status = UserSubscriptionStatus.ACTIVE
                fleet.stripe_latest_invoice_id = invoice_id or fleet.stripe_latest_invoice_id
                fleet.stripe_invoice_url = data_obj.get("hosted_invoice_url", fleet.stripe_invoice_url) or ""
                fleet.save(update_fields=[
                    "next_payment_date",
                    "status",
                    "stripe_latest_invoice_id",
                    "stripe_invoice_url",
                    "updated_at",
                ])
                if fleet.subscription and fleet.next_payment_date:
                    fleet.subscription.status = UserSubscriptionStatus.ACTIVE
                    fleet.subscription.payment_status = PaymentStatus.PAID
                    fleet.subscription.last_renew_at = timezone.now()
                    fleet.subscription.expires_at = timezone.make_aware(
                        datetime.combine(fleet.next_payment_date, time(hour=23, minute=59))
                    )
                    fleet.subscription.save(update_fields=[
                        "status",
                        "payment_status",
                        "last_renew_at",
                        "expires_at",
                        "updated_at",
                    ])
            elif data_obj.get("billing_reason") == "subscription_cycle":
                web_sub = UserSubscription.objects.filter(
                    stripe_subscription_id=stripe_sub_id,
                    fleet_accounts__isnull=True,
                ).first()
                if web_sub:
                    duration_days = 365 if web_sub.plan.billing_type == BillingType.YEARLY else 30
                    now = timezone.now()
                    base_dt = web_sub.expires_at if (web_sub.expires_at and web_sub.expires_at > now) else now
                    web_sub.status = UserSubscriptionStatus.ACTIVE
                    web_sub.payment_status = PaymentStatus.PAID
                    web_sub.last_renew_at = now
                    web_sub.expires_at = base_dt + timedelta(days=duration_days)
                    web_sub.save(update_fields=[
                        "status",
                        "payment_status",
                        "last_renew_at",
                        "expires_at",
                        "updated_at",
                    ])

    elif event_type in ("invoice.payment_failed", "customer.subscription.deleted"):
        if event_type == "invoice.payment_failed":
            stripe_sub_id = _extract_invoice_subscription_id(data_obj)
            new_status = UserSubscriptionStatus.FAILED
        else:
            stripe_sub_id = str(data_obj.get("id") or "")
            new_status = UserSubscriptionStatus.CANCELLED

        if stripe_sub_id:
            fleet = FleetAccount.objects.filter(stripe_subscription_id=stripe_sub_id).first()
            if fleet:
                fleet.status = new_status
                fleet.save(update_fields=["status", "updated_at"])
                if fleet.subscription:
                    fleet.subscription.status = new_status
                    fleet.subscription.save(update_fields=["status", "updated_at"])
            else:
                UserSubscription.objects.filter(stripe_subscription_id=stripe_sub_id).update(status=new_status)

    return event_type

