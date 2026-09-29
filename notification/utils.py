from django.contrib.contenttypes.models import ContentType

from core.constants import LogStatus
from notification.models import ActivityLog


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def log_activity(request, action, target_obj=None, message="", metadata=None, status=LogStatus.SUCCESS):
    if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
        return None

    entity_type = None
    entity_id = None
    if target_obj is not None:
        entity_type = ContentType.objects.get_for_model(target_obj, for_concrete_model=False)
        entity_id = getattr(target_obj, "id", None)

    return ActivityLog.objects.create(
        user=request.user,
        action=action,
        message=message,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=get_client_ip(request),
        device_info=request.headers.get("User-Agent", ""),
        metadata_json=metadata or {},
    )