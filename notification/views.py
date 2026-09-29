from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view

from core.constants import LogStatus, NotifyLogAction
from core.permissions import HasAdminDashboardPermission
from notification.models import ActivityLog
from notification.serializers import ActivityLogOptionsSerializer, ActivityLogSerializer


AUDIT_LOG_PERMISSION = "security_logging_compliance.audit_logs"
AUDIT_LOG_TAG = "Security - Audit Logs - Admin"


@extend_schema(tags=[AUDIT_LOG_TAG])
@extend_schema_view(
    list=extend_schema(
        operation_id="admin_audit_log_list",
        summary="List audit logs",
        description=(
            "Returns admin dashboard audit logs. Supports filtering by action, status, "
            "user, entity type, entity ID, IP address, and date range. "
            "Use this for Security / Logging / Compliance audit log tables."
        ),
        parameters=[
            OpenApiParameter("search", str, description="Search message, admin email, device info, IP address, or entity ID."),
            OpenApiParameter("action", str, enum=[choice.value for choice in NotifyLogAction], description="Filter by action."),
            OpenApiParameter("status", str, enum=[choice.value for choice in LogStatus], description="Filter by log status."),
            OpenApiParameter("user_id", str, description="Filter by admin/user UUID."),
            OpenApiParameter("user_email", str, description="Filter by admin/user email."),
            OpenApiParameter("entity_type", str, description="Filter by entity type as app_label.model, for example account.user."),
            OpenApiParameter("entity_id", int, description="Filter by target entity ID."),
            OpenApiParameter("ip_address", str, description="Filter by IP address."),
            OpenApiParameter("date_from", str, description="Created-at lower bound. Accepts YYYY-MM-DD or ISO datetime."),
            OpenApiParameter("date_to", str, description="Created-at upper bound. Accepts YYYY-MM-DD or ISO datetime."),
            OpenApiParameter("limit", int, description="Maximum rows to return. Default 100, max 500."),
            OpenApiParameter("offset", int, description="Rows to skip. Default 0."),
        ],
        responses={200: OpenApiResponse(response=ActivityLogSerializer(many=True))},
    ),
    retrieve=extend_schema(
        operation_id="admin_audit_log_retrieve",
        summary="Retrieve audit log",
        description="Returns one audit log entry by ID.",
        responses={
            200: OpenApiResponse(response=ActivityLogSerializer),
            404: OpenApiResponse(description="Audit log not found."),
        },
    ),
)
class AdminAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = AUDIT_LOG_PERMISSION
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        qs = ActivityLog.objects.select_related("user", "user__admin_profile", "entity_type").order_by("-created_at")
        params = self.request.query_params

        search = (params.get("search") or params.get("q") or "").strip()
        if search:
            search_filter = (
                Q(message__icontains=search)
                | Q(user__email__icontains=search)
                | Q(device_info__icontains=search)
                | Q(ip_address__icontains=search)
            )
            if search.isdigit():
                search_filter |= Q(entity_id=int(search))
            qs = qs.filter(search_filter)

        action_value = params.get("action")
        if action_value:
            qs = qs.filter(action=action_value.upper())

        status_value = params.get("status")
        if status_value:
            qs = qs.filter(status=status_value.upper())

        user_id = params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)

        user_email = params.get("user_email")
        if user_email:
            qs = qs.filter(user__email__iexact=user_email.strip())

        entity_id = params.get("entity_id")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)

        ip_address = params.get("ip_address")
        if ip_address:
            qs = qs.filter(ip_address=ip_address.strip())

        entity_type = (params.get("entity_type") or "").strip().lower()
        if entity_type:
            qs = self._filter_entity_type(qs, entity_type)

        date_from = self._parse_date_param(params.get("date_from"), end_of_day=False)
        if date_from:
            qs = qs.filter(created_at__gte=date_from)

        date_to = self._parse_date_param(params.get("date_to"), end_of_day=True)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)

        return qs

    def _filter_entity_type(self, qs, entity_type):
        if "." in entity_type:
            app_label, model = entity_type.split(".", 1)
            return qs.filter(entity_type__app_label=app_label, entity_type__model=model)
        return qs.filter(entity_type__model=entity_type)

    def _parse_date_param(self, value, end_of_day=False):
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed:
            return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        parsed_date = parse_date(value)
        if not parsed_date:
            return None
        suffix = "T23:59:59.999999" if end_of_day else "T00:00:00"
        parsed = parse_datetime(f"{parsed_date.isoformat()}{suffix}")
        return timezone.make_aware(parsed) if parsed and timezone.is_naive(parsed) else parsed

    def _get_limit_offset(self):
        try:
            limit = int(self.request.query_params.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        try:
            offset = int(self.request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        limit = min(max(limit, 1), 500)
        offset = max(offset, 0)
        return limit, offset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        total = queryset.count()
        limit, offset = self._get_limit_offset()
        page = queryset[offset:offset + limit]
        serializer = self.get_serializer(page, many=True)
        return Response({
            "success": True,
            "count": total,
            "limit": limit,
            "offset": offset,
            "data": serializer.data,
        }, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=[AUDIT_LOG_TAG],
        operation_id="admin_audit_log_options",
        summary="Get audit log filter options",
        description="Returns available action/status choices and logged entity types for audit-log filters.",
        responses={200: OpenApiResponse(response=ActivityLogOptionsSerializer)},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def filter_options(self, request):
        entity_type_ids = (
            ActivityLog.objects.exclude(entity_type__isnull=True)
            .values_list("entity_type_id", flat=True)
            .distinct()
        )
        content_types = ContentType.objects.filter(id__in=entity_type_ids).order_by("app_label", "model")
        return Response({
            "success": True,
            "data": {
                "actions": [{"value": value, "label": label} for value, label in NotifyLogAction.choices],
                "statuses": [{"value": value, "label": label} for value, label in LogStatus.choices],
                "entity_types": [
                    {
                        "value": f"{content_type.app_label}.{content_type.model}",
                        "label": f"{content_type.app_label}.{content_type.model}",
                        "app_label": content_type.app_label,
                        "model": content_type.model,
                    }
                    for content_type in content_types
                ],
            },
        }, status=status.HTTP_200_OK)
