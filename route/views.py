from rest_framework import generics, viewsets, views
from django.shortcuts import get_object_or_404
from .models import Route, RoutePermit, PermitWaypoint
from .serializers import (
    RouteListSerializer, RouteDetailSerializer, RouteCreateSerializer, PermitSerializers, WaypointSerializer, RouteBulkDeleteSerializer,
    AdminRouteHistoryListSerializer, AdminRouteHistoryDetailSerializer, AdminRouteWaypointSerializer
)
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework import status
from core.constants import RouteStatus
from core.viewsets import OwnModelViewSet
from core.permissions import HasAdminDashboardPermission, get_admin_dashboard_permissions
from rest_framework.exceptions import ValidationError, NotFound
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.db import transaction
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiTypes


@extend_schema(
    tags=["Route"],
    summary="Route ViewSets",
    description="Route ViewSets",
)
class RouteViewSets(OwnModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["id", "name", "status"]
    filterset_fields = ["status",]
    
    def get_serializer_class(self):
        if self.action == "create":
            return RouteCreateSerializer
        elif self.action == "retrieve":
            return RouteDetailSerializer
        return RouteListSerializer
    
    def get_queryset(self):
        # When drf-spectacular introspects views it may call get_queryset
        # without a normal request (or with an AnonymousUser). Guard against
        # that by returning an empty queryset for schema generation.
        if getattr(self, "swagger_fake_view", False):
            return Route.objects.none()

        return (
            Route.objects.prefetch_related(
                "permits",
                "permits__waypoints"
            ).filter(
                created_by=self.request.user
            )
        )
    
    def create_success_response(self, serializer):
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Route created successfully.",
                "route": {
                    "id": serializer.instance.id,
                    "name": serializer.instance.name
                }
            },
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["patch"], url_path="update-name")
    def update_name(self, request, pk=None):
        route = self.get_object()
        route.name = request.data.get("name", route.name)
        route.save(update_fields=["name"])
        return Response(
            {
                "success": True,
                "message": "Route name updated successfully.",
            },
            status=status.HTTP_200_OK
        )

        # -----------------------------
    
    # ROUTE PERMITs ALL VIEWS
    def get_permit(self, id):
        try:
            return get_object_or_404(RoutePermit, pk=id, route=self.get_object())
        except RoutePermit.DoesNotExist:
            raise NotFound(
                detail="Route Permit Not Found with this id.",
                code=status.HTTP_404_NOT_FOUND
            )
    
    def get_all_permit(self):
        return self.get_object().permits.all()

    @action(detail=True, methods=["post"])
    def permit(self, request, *args, **kwargs):
        try:
            serializer = PermitSerializers(data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save(route=self.get_object())
            return Response(
                {
                    "success": True,
                    "data": serializer.data
                }, status=status.HTTP_201_CREATED
            )
        except ValidationError as e:
            detail = e.detail if hasattr(e, "detail") else e
            if isinstance(detail, list):
                error = detail[0].__str__()
            elif isinstance(detail, dict):
                error = {
                    key: (
                        value[0] if isinstance(value, list) else str(value)
                    )
                    for key, value in detail.items()
                }
            else:
                error = str(detail)
            return Response(
                {
                    "success": False,
                    "detail": error,
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)")
    def permit_detail(self, request, pk=None, permit_id=None):
        route = self.get_object()
        permit = get_object_or_404(
            route.permits.select_related("route"),
            id=permit_id
        )
        serializer = PermitSerializers(permit, context={"request": request})
        return Response(
            {
                "success": True,
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    @permit_detail.mapping.delete
    def permit_details_delete(self, request, pk=None, permit_id=None):
        try:
            route = self.get_object()
            permit = RoutePermit.objects.get(
                route=route,
                id=permit_id
            )
            permit.delete()
            return Response(
                {
                    "success": True,
                    "message": "Deleted!"
                }, status=status.HTTP_200_OK
            )
        except RoutePermit.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )

    @permit_detail.mapping.patch
    def permit_details_update(self, request, pk=None, permit_id=None):
        try:
            route = self.get_object()
            permit = RoutePermit.objects.get(route=route,id=permit_id)
            serializer = PermitSerializers(permit, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    "success": True,
                    "data": serializer.data
                }, status=status.HTTP_200_OK
            )
        except RoutePermit.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )


    # -----------------------------
    # PERMIT WAYPOINTS ALL VIEWS
    def get_permit_waypoint(self, permit, id):
        try:
            return get_object_or_404(PermitWaypoint, pk=id, permit=permit)
        except PermitWaypoint.DoesNotExist:
            raise NotFound(detail="Permit Waypoint Not Found with this id.", code=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)/waypoint")
    def waypoint(self, request, pk=None, permit_id=None):
        try:
            route = self.get_object()
            permit = RoutePermit.objects.get(route=route,id=permit_id)
            waypoints = permit.waypoints.order_by('index')
            serializer = WaypointSerializer(waypoints, many=True)
            return Response({
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        except RoutePermit.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )
    
    @waypoint.mapping.post
    def add_waypoint(self, request, pk=None, permit_id=None):
        try:
            route = self.get_object()
            permit = RoutePermit.objects.get(route=route,id=permit_id)
            last_waypoint = permit.waypoints.order_by('index').last()
            next_index = last_waypoint.index + 1 if last_waypoint else 1
            serializer = WaypointSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(permit=permit,index=next_index)
            return Response({
                "success": True,
                "message": "Waypoint added successfully.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        except RoutePermit.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)/waypoint/(?P<waypoint_id>[^/.]+)")
    def waypoint_details(self, request, pk=None, permit_id=None, waypoint_id=None):
        try:
            permit = self.get_permit(permit_id)
            waypoint = self.get_permit_waypoint(permit, waypoint_id)
            serializer = WaypointSerializer(waypoint)
            return Response({
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        except NotFound as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )
    
    @waypoint_details.mapping.patch
    def waypoint_details_update(self, request, pk=None, permit_id=None, waypoint_id=None):
        try:
            permit = self.get_permit(permit_id)
            waypoint = self.get_permit_waypoint(permit, waypoint_id)
            serializer = WaypointSerializer(waypoint, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    "success": True,
                    "data": serializer.data
                }, status=status.HTTP_200_OK
            )
        except NotFound as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )
    
    @waypoint_details.mapping.delete
    def waypoint_details_delete(self, request, pk=None, permit_id=None, waypoint_id=None):
        try:
            permit = self.get_permit(permit_id)
            waypoint = self.get_permit_waypoint(permit, waypoint_id)
            waypoint.delete()
            return Response(
                {
                    "success": True,
                    "message": "Deleted!"
                }, status=status.HTTP_200_OK
            )
        except NotFound as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                }, status=status.HTTP_404_NOT_FOUND
            )
     
    # -----------------------------
    
    # -----------------------------
    # START ROUTE
    @action(detail=True, methods=["post"], url_path="drive-start")
    def start_drive_route(self, request, pk=None):
        route = self.get_object()
        route.status = RouteStatus.START
        route.started_at = timezone.now()
        route.save(update_fields=["status", "started_at"])
        return Response({
            "success": True,
            "message": "Route Drive started successfully."
        }, status=status.HTTP_200_OK)
    
    # START ROUTE
    @action(detail=True, methods=["post"], url_path="drive-stop")
    def stop_drive_route(self, request, pk=None):
        route = self.get_object()
        route.status = RouteStatus.STOP
        route.started_at = timezone.now()
        route.save(update_fields=["status", "started_at"])
        return Response({
            "success": True,
            "message": "Route Drive Stoped."
        }, status=status.HTTP_200_OK)

    # COMPLETE ROUTE
    @action(detail=True, methods=["post"], url_path="drive-complete")
    def complete_drive_route(self, request, pk=None):
        route = self.get_object()
        route.status = RouteStatus.COMPLETED
        route.completed_at = timezone.now()
        route.route_progress_percentage = "100"
        route.save(update_fields=["status", "started_at"])

        return Response({
            "success": True,
            "message": "Route completed successfully."
        }, status=status.HTTP_200_OK)

    # CANCEL ROUTE
    @action(detail=True, methods=["post"], url_path="drive-cancel")
    def cancel_drive_route(self, request, pk=None):
        route = self.get_object()
        route.status = RouteStatus.CANCELLED
        route.cancelled_at = timezone.now()
        route.save(update_fields=["status", "started_at"])

        return Response({
            "success": True,
            "message": "Route cancelled."
        }, status=status.HTTP_200_OK)

    # -----------------------------
    
    # -----------------------------
    # GET ROUTE PERMIT STARTING POINT
    def get_last_permit(self):
        route = self.get_object()
        permit = route.permits.all().last()
        return permit

    @action(detail=True, methods=["get"], url_path="permit-starting-point")
    def permit_starting_point(self, request, *args, **kwargs):
        try:
            last_permit = self.get_last_permit()
            if last_permit:
                response = {
                    "start_location_name": last_permit.end_location,
                    "start_latitude": last_permit.end_latitude,
                    "start_longitude": last_permit.end_longitude
                }
            else:
                response = None
            return Response(
                {
                    "status": True,
                    "data": response
                }, status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {
                    "status": False,
                    "message": str(e)
                }, status=status.HTTP_400_BAD_REQUEST
            )
    
    # -----------------------------
    
    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = RouteBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        route_ids = serializer.validated_data["route_ids"]
        with transaction.atomic():
            routes = Route.objects.filter(
                id__in=route_ids,
                created_by=request.user
            )
            deleted_count = routes.count()
            routes.delete()
        return Response(
            {
                "success": True,
                "message": f"{deleted_count} routes deleted successfully."
            },
            status=status.HTTP_200_OK
        )
        
    @action(detail=True, methods=["post"], url_path="duplicate-route")
    def duplicate_route(self, request, pk=None):
        try:
            source_route = self.get_object()
            with transaction.atomic():
                new_route = Route.objects.create(
                    created_by=request.user,
                    team=source_route.team,
                    name=f"{source_route.name} (Copy)",
                    description=source_route.description,
                    status=RouteStatus.DRAFT,
                    total_distance_km=source_route.total_distance_km,
                    estimated_duration=source_route.estimated_duration,
                    total_waypoints=source_route.total_waypoints,
                )
                for permit in source_route.permits.all():
                    old_waypoints = permit.waypoints.all()
                    new_permit = RoutePermit.objects.create(
                        route=new_route,
                        index=permit.index,
                        name=permit.name,
                        start_location=permit.start_location,
                        start_latitude=permit.start_latitude,
                        start_longitude=permit.start_longitude,
                        end_location=permit.end_location,
                        end_latitude=permit.end_latitude,
                        end_longitude=permit.end_longitude,
                        permit_text=permit.permit_text,
                        extracted_text=permit.extracted_text,
                        ai_response_json=permit.ai_response_json,
                        processing_status=permit.processing_status,
                        confidence_score=permit.confidence_score,
                    )

                    waypoint_objects = []
                    for wp in old_waypoints:
                        waypoint_objects.append(
                            PermitWaypoint(
                                permit=new_permit,
                                route=new_route,
                                index=wp.index,
                                name=wp.name,
                                waypoint_type=wp.waypoint_type,
                                latitude=wp.latitude,
                                longitude=wp.longitude,
                                description=wp.description,
                                icon=wp.icon,
                                eta_minutes=wp.eta_minutes,
                            )
                        )
                    PermitWaypoint.objects.bulk_create(waypoint_objects)
            return Response(
                {
                    "success": True,
                    "message": "Route duplicated successfully.",
                    "route": {
                        "id": new_route.id,
                        "name": new_route.name,
                    }
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

class AdminRouteHistoryPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminRouteHistoryQueryMixin:
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = ["user_accounts", "user_accounts.single", "user_accounts.teams", "user_accounts.fleet"]

    ordering_map = {
        "created_at": "created_at",
        "-created_at": "-created_at",
        "name": "name",
        "-name": "-name",
        "status": "status",
        "-status": "-status",
        "total_distance_km": "total_distance_km",
        "-total_distance_km": "-total_distance_km",
        "total_waypoints": "total_waypoints",
        "-total_waypoints": "-total_waypoints",
        "driver_email": "created_by__email",
        "-driver_email": "-created_by__email",
    }

    def parse_datetime_param(self, value, end_of_day=False):
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

    def get_allowed_account_types(self):
        user = self.request.user
        if user.is_superuser:
            return {"single", "team", "fleet"}

        perms = set(get_admin_dashboard_permissions(user))
        if "user_accounts" in perms:
            return {"single", "team", "fleet"}

        allowed = set()
        if "user_accounts.single" in perms:
            allowed.add("single")
        if "user_accounts.teams" in perms:
            allowed.add("team")
        if "user_accounts.fleet" in perms:
            allowed.add("fleet")
        return allowed

    def base_queryset(self):
        return (
            Route.objects.select_related("created_by", "team")
            .prefetch_related("permits")
            .annotate(permit_count=Count("permits", distinct=True))
        )

    def apply_account_scope(self, queryset):
        requested_type = (self.request.query_params.get("account_type") or "").strip().lower()
        allowed_types = self.get_allowed_account_types()

        if requested_type:
            if requested_type not in {"single", "team", "fleet"}:
                return queryset.none()
            if requested_type not in allowed_types:
                return queryset.none()
            account_types = {requested_type}
        else:
            account_types = allowed_types

        if not account_types:
            return queryset.none()

        type_filter = Q()
        if "single" in account_types:
            type_filter |= Q(team__isnull=True)
        if "team" in account_types:
            type_filter |= Q(team__isnull=False)
        if "fleet" in account_types:
            # Fleet data is not modeled yet, so this intentionally adds no rows.
            type_filter |= Q(pk__in=[])
        return queryset.filter(type_filter)

    def get_filtered_queryset(self):
        params = self.request.query_params
        queryset = self.apply_account_scope(self.base_queryset())

        user_id = params.get("user_id")
        if user_id:
            queryset = queryset.filter(created_by_id=user_id)

        user_email = params.get("user_email")
        if user_email:
            queryset = queryset.filter(created_by__email__iexact=user_email.strip())

        team_id = params.get("team_id")
        if team_id:
            queryset = queryset.filter(team_id=team_id)

        fleet_id = params.get("fleet_id")
        if fleet_id:
            queryset = queryset.none()

        status_value = params.get("status")
        if status_value:
            queryset = queryset.filter(status__iexact=status_value.strip())

        search = params.get("search") or params.get("q")
        if search:
            search = search.strip()
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(created_by__email__icontains=search)
                | Q(team__name__icontains=search)
            )

        date_from = self.parse_datetime_param(params.get("date_from"), end_of_day=False)
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)

        date_to = self.parse_datetime_param(params.get("date_to"), end_of_day=True)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)

        ordering = self.ordering_map.get(params.get("ordering"), "-created_at")
        return queryset.order_by(ordering, "-id")


@extend_schema(
    tags=["Route History - Admin"],
    operation_id="admin_route_history_list",
    summary="List admin route history",
    description=(
        "Lists route records for admin dashboard route-history pages. "
        "Supports filtering by user email/user ID, account type, team, search, status, date range, and ordering. "
        "Fleet filters are accepted but return no rows until fleet support is implemented."
    ),
    parameters=[
        OpenApiParameter("user_email", OpenApiTypes.EMAIL, description="Filter by route creator email."),
        OpenApiParameter("user_id", OpenApiTypes.INT, description="Filter by route creator user ID."),
        OpenApiParameter("account_type", OpenApiTypes.STR, enum=["single", "team", "fleet"], description="Filter by account type."),
        OpenApiParameter("team_id", OpenApiTypes.INT, description="Filter by team ID."),
        OpenApiParameter("fleet_id", OpenApiTypes.INT, description="Accepted for future fleet support; currently returns no rows."),
        OpenApiParameter("search", OpenApiTypes.STR, description="Search route name, description, driver email, or team name."),
        OpenApiParameter("status", OpenApiTypes.STR, description="Filter by route status."),
        OpenApiParameter("date_from", OpenApiTypes.STR, description="Created-at lower bound. YYYY-MM-DD or ISO datetime."),
        OpenApiParameter("date_to", OpenApiTypes.STR, description="Created-at upper bound. YYYY-MM-DD or ISO datetime."),
        OpenApiParameter("page", OpenApiTypes.INT, description="Page number."),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="Page size, max 100."),
        OpenApiParameter("ordering", OpenApiTypes.STR, description="One of created_at, -created_at, name, -name, status, -status, total_distance_km, -total_distance_km, total_waypoints, -total_waypoints, driver_email, -driver_email."),
    ],
    responses={200: OpenApiResponse(response=AdminRouteHistoryListSerializer(many=True))},
)
class AdminRouteHistoryListView(AdminRouteHistoryQueryMixin, views.APIView):
    pagination_class = AdminRouteHistoryPagination

    def get(self, request):
        queryset = self.get_filtered_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = AdminRouteHistoryListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


@extend_schema(
    tags=["Route History - Admin"],
    operation_id="admin_route_history_retrieve",
    summary="Retrieve admin route history detail",
    responses={200: AdminRouteHistoryDetailSerializer},
)
class AdminRouteHistoryDetailView(AdminRouteHistoryQueryMixin, views.APIView):
    def get(self, request, route_id):
        route = get_object_or_404(self.get_filtered_queryset(), id=route_id)
        serializer = AdminRouteHistoryDetailSerializer(route, context={"request": request})
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Route History - Admin"],
    operation_id="admin_route_history_waypoints",
    summary="List admin route history waypoints",
    responses={200: AdminRouteWaypointSerializer(many=True)},
)
class AdminRouteHistoryWaypointsView(AdminRouteHistoryQueryMixin, views.APIView):
    def get(self, request, route_id):
        route = get_object_or_404(self.get_filtered_queryset(), id=route_id)
        waypoints = (
            PermitWaypoint.objects.filter(Q(route=route) | Q(permit__route=route))
            .distinct()
            .order_by("index", "id")
        )
        serializer = AdminRouteWaypointSerializer(waypoints, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


