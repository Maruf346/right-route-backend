from django.db import transaction

from .models import PurchaseInfo


@transaction.atomic
def create_or_update_purchase_info(
    *,
    user,
    subscription=None,
    platform,
    product_id,
    transaction_id,
    purchase_token=None,
    receipt_data=None,
    package_name=None,
    original_transaction_id=None,
    order_id=None,
    purchase_time=None,
    expiry_time=None,
    auto_renew=False,
    verification_status=None,
    raw_response=None,
):
    purchase, created = PurchaseInfo.objects.update_or_create(
        transaction_id=transaction_id,
        defaults={
            "user": user,
            "subscription": subscription,
            "platform": platform,
            "product_id": product_id,
            "purchase_token": purchase_token,
            "receipt_data": receipt_data,
            "package_name": package_name,
            "original_transaction_id": original_transaction_id,
            "order_id": order_id,
            "purchase_time": purchase_time,
            "expiry_time": expiry_time,
            "auto_renew": auto_renew,
            "verification_status": verification_status,
            "raw_response": raw_response or {},
        },
    )

    return purchase, created


