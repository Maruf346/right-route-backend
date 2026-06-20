from rest_framework import generics, viewsets, views
from django.shortcuts import get_object_or_404
from .models import Route, RoutePermit, PermitWaypoint
# from .serializers import (
#     CreateRouteSerializer, AddPermitSerializer, WaypointSerializer,
#     RouteSerializer, RouteCreateSerializer, RouteDetailSerializer, PermitSerializers, WaypointSerializer
# )
from .new_serializers import (
    RouteListSerializer, RouteDetailSerializer, RouteCreateSerializer, PermitSerializers
)
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status
from core.constants import RouteStatus
from core.viewsets import OwnModelViewSet
from rest_framework.exceptions import ValidationError, NotFound
from django.utils import timezone

class RouteViewSets(OwnModelViewSet):
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == "create":
            return RouteCreateSerializer
        elif self.action == "retrieve":
            return RouteDetailSerializer
        return RouteListSerializer
    
    def get_queryset(self):
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
                "data": self.get_serializer(serializer.instance).data
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
            # return self.get_all_permit(pk=id)
            return get_object_or_404(RoutePermit, pk=id, route=self.get_object())
        except RoutePermit.DoesNotExist:
            raise NotFound(
                detail="Route Permit Not Found with this id.",
                code=status.HTTP_404_NOT_FOUND
            )
    
    def get_all_permit(self):
        return self.get_object().permits.all()

    @action(detail=True, methods=["get"])
    def permit(self, request, *args, **kwargs):
        route = self.get_object()
        serializer = PermitSerializers(
            self.get_all_permit(), many=True, context={"request": request}
        )
        permit = serializer.data
        return Response(
            {
                "success": True,
                "data": {
                    "route_name": route.name,
                    "status": route.status,
                    "route_is_completed": route.is_completed,
                    "is_permit": len(permit) > 0,
                    "count": len(permit),
                    "permit": permit
                }
            }
        )

    @permit.mapping.post
    def add_permit(self, request, *args, **kwargs):
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
            route = self.get_object()
            permit = self.get_route_permit(route, permit_id)
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
            route = self.get_object()
            permit = self.get_route_permit(route, permit_id)
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
            route = self.get_object()
            permit = self.get_route_permit(route, permit_id)
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


# class RouteViewSets(OwnModelViewSet):
#     permission_classes = [IsAuthenticated]
#     parser_classes = (MultiPartParser, FormParser)

#     def get_queryset(self):
#         return (
#             Route.objects
#             .select_related("created_by", "team")
#             .prefetch_related("permits")
#             .filter(created_by=self.request.user)
#             .order_by("-created_at")
#         )
    
#     def get_serializer_class(self):
#         if self.action == "create":
#             return RouteCreateSerializer
#         if self.action == "retrieve":
#             return RouteDetailSerializer
#         return RouteSerializer
    
#     def create_success_response(self, serializer):
#         serializer.save()
#         return Response(
#             {
#                 "success": True,
#                 "message": "Route created successfully.",
#                 "data": RouteSerializer(serializer.instance).data
#             },
#             status=status.HTTP_201_CREATED
#         )
    
    
#     # -----------------------------
#     # ROUTE PERMITs ALL VIEWS
#     def get_route_permit(self, route, id):
#         try:
#             return get_object_or_404(RoutePermit, pk=id, route=route)
#         except RoutePermit.DoesNotExist:
#             raise NotFound(detail="Route Permit Not Found with this id.", code=status.HTTP_404_NOT_FOUND)
    
#     @action(detail=True, methods=["get"])
#     def permit(self, request, *args, **kwargs):
#         route = self.get_object()
#         permits = route.permits.all()
#         serializer = PermitSerializers(permits, many=True, context={"request": request})
#         permit = serializer.data
#         return Response(
#             {
#                 "success": True,
#                 "data": {
#                     "route_name": route.name,
#                     "route_description": route.description,
#                     "status": route.status,
#                     "route_is_completed": route.is_completed,
#                     "is_permit": len(permit) > 0,
#                     "count": len(permit),
#                     "permit": permit
#                 }
#             }
#         )
    
#     @permit.mapping.post
#     def add_permit(self, request, *args, **kwargs):
#         try:
#             serializer = PermitSerializers(data=request.data, context={"request": request})
#             serializer.is_valid(raise_exception=True)
#             serializer.save(route=self.get_object())
#             return Response(
#                 {
#                     "success": True,
#                     "data": serializer.data
#                 }, status=status.HTTP_201_CREATED
#             )
#         except ValidationError as e:
#             detail = e.detail if hasattr(e, "detail") else e
            
#             if isinstance(detail, list):
#                 error = detail[0].__str__()
#             elif isinstance(detail, dict):
#                 error = {
#                     key: (
#                         value[0] if isinstance(value, list) else str(value)
#                     )
#                     for key, value in detail.items()
#                 }
#             else:
#                 error = str(detail)
#             return Response(
#                 {
#                     "success": False,
#                     "detail": error,
#                 },
#                 status=status.HTTP_400_BAD_REQUEST
#             )
    
#     @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)")
#     def permit_detail(self, request, pk=None, permit_id=None):
#         route = self.get_object()
#         permit = get_object_or_404(
#             route.permits.select_related("route"),
#             id=permit_id
#         )
#         serializer = PermitSerializers(permit, context={"request": request})
#         return Response(
#             {
#                 "success": True,
#                 "data": serializer.data
#             },
#             status=status.HTTP_200_OK
#         )
    
#     @permit_detail.mapping.delete
#     def permit_details_delete(self, request, pk=None, permit_id=None):
#         try:
#             route = self.get_object()
#             permit = RoutePermit.objects.get(
#                 route=route,
#                 id=permit_id
#             )
#             permit.delete()
#             return Response(
#                 {
#                     "success": True,
#                     "message": "Deleted!"
#                 }, status=status.HTTP_200_OK
#             )
#         except RoutePermit.DoesNotExist as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     @permit_detail.mapping.patch
#     def permit_details_update(self, request, pk=None, permit_id=None):
#         try:
#             route = self.get_object()
#             permit = RoutePermit.objects.get(route=route,id=permit_id)
#             serializer = PermitSerializers(permit, data=request.data, partial=True)
#             serializer.is_valid(raise_exception=True)
#             serializer.save()
#             return Response(
#                 {
#                     "success": True,
#                     "data": serializer.data
#                 }, status=status.HTTP_200_OK
#             )
#         except RoutePermit.DoesNotExist as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     # -----------------------------
    
#     # -----------------------------
#     # PERMIT WAYPOINTS ALL VIEWS
#     def get_permit_waypoint(self, permit, id):
#         try:
#             return get_object_or_404(PermitWaypoint, pk=id, permit=permit)
#         except PermitWaypoint.DoesNotExist:
#             raise NotFound(detail="Permit Waypoint Not Found with this id.", code=status.HTTP_404_NOT_FOUND)
    
#     @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)/waypoint")
#     def waypoint(self, request, pk=None, permit_id=None):
#         try:
#             route = self.get_object()
#             permit = RoutePermit.objects.get(route=route,id=permit_id)
#             waypoints = permit.waypoints.order_by('index')
#             serializer = WaypointSerializer(waypoints, many=True)
#             return Response({
#                 "success": True,
#                 "data": serializer.data
#             }, status=status.HTTP_200_OK)
#         except RoutePermit.DoesNotExist as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     @waypoint.mapping.post
#     def add_waypoint(self, request, pk=None, permit_id=None):
#         try:
#             route = self.get_object()
#             permit = RoutePermit.objects.get(route=route,id=permit_id)
#             last_waypoint = permit.waypoints.order_by('index').last()
#             next_index = last_waypoint.index + 1 if last_waypoint else 1
#             serializer = WaypointSerializer(data=request.data)
#             serializer.is_valid(raise_exception=True)
#             serializer.save(permit=permit,index=next_index)
#             return Response({
#                 "success": True,
#                 "message": "Waypoint added successfully.",
#                 "data": serializer.data
#             }, status=status.HTTP_201_CREATED)
#         except RoutePermit.DoesNotExist as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)/waypoint/(?P<waypoint_id>[^/.]+)")
#     def waypoint_details(self, request, pk=None, permit_id=None, waypoint_id=None):
#         try:
#             route = self.get_object()
#             permit = self.get_route_permit(route, permit_id)
#             waypoint = self.get_permit_waypoint(permit, waypoint_id)
#             serializer = WaypointSerializer(waypoint)
#             return Response({
#                 "success": True,
#                 "data": serializer.data
#             }, status=status.HTTP_200_OK)
#         except NotFound as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     @waypoint_details.mapping.patch
#     def waypoint_details_update(self, request, pk=None, permit_id=None, waypoint_id=None):
#         try:
#             route = self.get_object()
#             permit = self.get_route_permit(route, permit_id)
#             waypoint = self.get_permit_waypoint(permit, waypoint_id)
#             serializer = WaypointSerializer(waypoint, data=request.data, partial=True)
#             serializer.is_valid(raise_exception=True)
#             serializer.save()
#             return Response(
#                 {
#                     "success": True,
#                     "data": serializer.data
#                 }, status=status.HTTP_200_OK
#             )
#         except NotFound as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
    
#     @waypoint_details.mapping.delete
#     def waypoint_details_delete(self, request, pk=None, permit_id=None, waypoint_id=None):
#         try:
#             route = self.get_object()
#             permit = self.get_route_permit(route, permit_id)
#             waypoint = self.get_permit_waypoint(permit, waypoint_id)
#             waypoint.delete()
#             return Response(
#                 {
#                     "success": True,
#                     "message": "Deleted!"
#                 }, status=status.HTTP_200_OK
#             )
#         except NotFound as e:
#             return Response(
#                 {
#                     "success": False,
#                     "message": str(e)
#                 }, status=status.HTTP_404_NOT_FOUND
#             )
     
#     # -----------------------------
    
#     # -----------------------------
#     # START ROUTE
#     @action(detail=True, methods=["post"], url_path="drive-start")
#     def start_drive_route(self, request, pk=None):
#         route = self.get_object()
#         route.status = RouteStatus.START
#         route.started_at = timezone.now()
#         route.save(update_fields=["status", "started_at"])
#         return Response({
#             "success": True,
#             "message": "Route Drive started successfully."
#         }, status=status.HTTP_200_OK)
    
#     # START ROUTE
#     @action(detail=True, methods=["post"], url_path="drive-stop")
#     def stop_drive_route(self, request, pk=None):
#         route = self.get_object()
#         route.status = RouteStatus.STOP
#         route.started_at = timezone.now()
#         route.save(update_fields=["status", "started_at"])
#         return Response({
#             "success": True,
#             "message": "Route Drive Stoped."
#         }, status=status.HTTP_200_OK)

#     # COMPLETE ROUTE
#     @action(detail=True, methods=["post"], url_path="drive-complete")
#     def complete_drive_route(self, request, pk=None):
#         route = self.get_object()
#         route.status = RouteStatus.COMPLETED
#         route.completed_at = timezone.now()
#         route.route_progress_percentage = "100"
#         route.save(update_fields=["status", "started_at"])

#         return Response({
#             "success": True,
#             "message": "Route completed successfully."
#         }, status=status.HTTP_200_OK)

#     # CANCEL ROUTE
#     @action(detail=True, methods=["post"], url_path="drive-cancel")
#     def cancel_drive_route(self, request, pk=None):
#         route = self.get_object()
#         route.status = RouteStatus.CANCELLED
#         route.cancelled_at = timezone.now()
#         route.save(update_fields=["status", "started_at"])

#         return Response({
#             "success": True,
#             "message": "Route cancelled."
#         }, status=status.HTTP_200_OK)

#     # -----------------------------
    
#     # -----------------------------
#     # GET ROUTE PERMIT STARTING POINT
#     def get_last_permit(self):
#         route = self.get_object()
#         permit = route.permits.all().last()
#         return permit

#     @action(detail=True, methods=["get"], url_path="permit-starting-point")
#     def permit_starting_point(self, request, *args, **kwargs):
#         try:
#             last_permit = self.get_last_permit()
#             if last_permit:
#                 response = {
#                     "start_location_name": last_permit.end_location,
#                     "start_latitude": last_permit.end_latitude,
#                     "start_longitude": last_permit.end_longitude
#                 }
#             else:
#                 response = None
#             return Response(
#                 {
#                     "status": True,
#                     "data": response
#                 }, status=status.HTTP_200_OK
#             )
#         except Exception as e:
#             return Response(
#                 {
#                     "status": False,
#                     "message": str(e)
#                 }, status=status.HTTP_400_BAD_REQUEST
#             )
    
#     # -----------------------------



