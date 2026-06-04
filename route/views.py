from rest_framework import generics, viewsets, views
from django.shortcuts import get_object_or_404
from .models import Route, RoutePermit, PermitWaypoint
from .serializers import (
    # CreateRouteSerializer, AddPermitSerializer, WaypointSerializer,
    RouteSerializer, RouteCreateSerializer, RouteDetailSerializer, RoutePermitSerializer, PermitSerializers, WaypointSerializer
)
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status
from core.constants import RouteStatus
from core.viewsets import OwnModelViewSet
from rest_framework.exceptions import ValidationError

class RouteViewSets(OwnModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        return (
            Route.objects
            .select_related("created_by", "team")
            .prefetch_related("permits")
            .filter(created_by=self.request.user)
            .order_by("-created_at")
        )
    
    def get_serializer_class(self):
        if self.action == "create":
            return RouteCreateSerializer
        if self.action == "retrieve":
            return RouteDetailSerializer
        return RouteSerializer
    
    def create_success_response(self, serializer):
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Route created successfully.",
                "data": RouteSerializer(serializer.instance).data
            },
            status=status.HTTP_201_CREATED
        )
    
    
    
    # -----------------------------
    # ROUTE PERMITs ALL VIEWS
    @action(detail=True, methods=["get"])
    def permit(self, request, *args, **kwargs):
        route = self.get_object()
        permits = route.permits.all()
        serializer = PermitSerializers(permits, many=True)
        permit = serializer.data
        return Response(
            {
                "success": True,
                "data": {
                    "route_name": route.name,
                    "route_description": route.description,
                    "route_status": route.route_status,
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
            serializer = PermitSerializers(data=request.data)
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
    
    @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)")
    def permit_detail(self, request, pk=None, permit_id=None):
        route = self.get_object()
        permit = get_object_or_404(
            route.permits.select_related("route"),
            id=permit_id
        )
        serializer = PermitSerializers(permit)
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
    
    # -----------------------------
    # PERMIT WAYPOINTS ALL VIEWS
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
    
    # @action(detail=True, methods=["get"], url_path="permit/(?P<permit_id>[^/.]+)/waypoint")
    # def waypoint(self, request, pk=None, permit_id=None):
    #     try:
    #         route = self.get_object()
    #         permit = RoutePermit.objects.get(route=route,id=permit_id)
    #         last_waypoint = permit.waypoints.order_by('index').last()
    #         next_index = last_waypoint.index + 1 if last_waypoint else 1
    #         serializer = WaypointSerializer(data=request.data)
    #         serializer.is_valid(raise_exception=True)
    #         serializer.save(permit=permit,index=next_index)
    #         return Response({
    #             "success": True,
    #             "message": "Waypoint added successfully.",
    #             "data": serializer.data
    #         }, status=status.HTTP_201_CREATED)
    #         return Response(
    #             {
    #                 "success": True,
    #                 "message": "Deleted!"
    #             }, status=status.HTTP_200_OK
    #         )
    #     except RoutePermit.DoesNotExist as e:
    #         return Response(
    #             {
    #                 "success": False,
    #                 "message": str(e)
    #             }, status=status.HTTP_404_NOT_FOUND
    #         )
        
        
        
        
        
        
    # -----------------------------


    
    # -----------------------------
    # START ROUTE
    @action(detail=True, methods=["post"], url_path="start")
    def start_route(self, request, pk=None):

        route = self.get_object()

        route.route_status = RouteStatus.IN_PROGRESS
        route.started_at = timezone.now()
        route.save()

        return Response({
            "success": True,
            "message": "Route started successfully."
        })

    # -----------------------------
    # COMPLETE ROUTE
    @action(detail=True, methods=["post"], url_path="complete")
    def complete_route(self, request, pk=None):

        route = self.get_object()

        route.route_status = RouteStatus.COMPLETED
        route.completed_at = timezone.now()
        route.route_progress_percentage = "100"
        route.save()

        return Response({
            "success": True,
            "message": "Route completed successfully."
        })

    # -----------------------------
    # CANCEL ROUTE
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_route(self, request, pk=None):

        route = self.get_object()

        route.route_status = RouteStatus.CANCELLED
        route.cancelled_at = timezone.now()
        route.save()

        return Response({
            "success": True,
            "message": "Route cancelled."
        })

# class RouteCreateAPIView(generics.CreateAPIView):
#     serializer_class = CreateRouteSerializer
#     permission_classes = [IsAuthenticated]

# class RouteListAPIView(generics.ListAPIView):
#     queryset = Route.objects.filter(status=RouteStatus.DRAFT)
#     serializer_class = CreateRouteSerializer
#     permission_classes = [IsAuthenticated]

# class RouteRetrieveAPIView(generics.RetrieveAPIView):
#     queryset = Route.objects.all()
#     serializer_class = CreateRouteSerializer
#     permission_classes = [AllowAny]

# class PermitViewset(viewsets.ModelViewSet):
#     queryset = RoutePermit.objects.all()
#     serializer_class = AddPermitSerializer
#     permission_classes = [AllowAny]
#     parser_classes = (MultiPartParser, FormParser)


#     @action(detail=False, methods=['post'], url_path='drive-start')
#     def drive_start(self, request, *args, **kwargs):
#         route = self.get_route()
#         route.status = RouteStatus.START
#         route.save(update_fields=["status"])
#         return Response(
#             {
#                 "success": True,
#                 "message": "Drive Stared!"
#             }
#         )
    
#     @action(detail=False, methods=['post'], url_path='drive-stop')
#     def drive_stop(self, request, *args, **kwargs):
#         route = self.get_route()
#         route.status = RouteStatus.STOP
#         route.save(update_fields=["status"])
#         return Response(
#             {
#                 "success": True,
#                 "message": "Drive Stoped!"
#             }
#         )
    
    
#     @action(detail=True, methods=['GET', 'patch'], url_path='update-waypoint/(?P<waypoint_id>[^/.]+)')
#     def update_waypoint(self, request, route_pk=None, pk=None, waypoint_id=None):
#         permit = self.get_object()
#         waypoint = get_object_or_404(Waypoint, pk=waypoint_id, permit=permit)
        
#         if request.method == "GET":
#             return Response(
#                 {
#                     "success": True,
#                     "data": WaypointSerializer(waypoint).data
#                 }
#             )
        
#         serializer = WaypointSerializer(waypoint, data=request.data, partial=True)
#         serializer.is_valid(raise_exception=True)
#         serializer.save()
#         return Response({
#             "success": True,
#             "message": "Waypoint updated successfully.",
#             "data": serializer.data
#         })

#     @action(detail=True, methods=['delete'], url_path='remove-waypoint/(?P<waypoint_id>[^/.]+)')
#     def remove_waypoint(self, request, route_pk=None, pk=None, waypoint_id=None):
#         permit = self.get_object()
#         waypoint = get_object_or_404(Waypoint, pk=waypoint_id, permit=permit)
#         waypoint.delete()
#         remaining_waypoints = permit.waypoints.order_by('order')
#         for index, wp in enumerate(remaining_waypoints, start=1):
#             wp.order = index
#         Waypoint.objects.bulk_update(
#             remaining_waypoints,
#             ['order']
#         )
#         return Response({
#             "success": True,
#             "message": "Waypoint removed successfully."
#         })
    

# class GetPermitStartingPoint(views.APIView):
#     def get_route(self):
#         route_pk = self.kwargs.get("route_pk", None)
#         if route_pk is None:
#             raise Exception("Route id not found.")
#         route = get_object_or_404(Route, pk=route_pk)
#         if not route:
#             raise Exception("Route not found with this id.")
#         return route
    
#     def get_last_permit(self):
#         route = self.get_route()
#         permit = route.permits.all().last()
#         return permit
    
#     def get(self, request, *args, **kwargs):
#         try:
#             last_permit = self.get_last_permit()
#             if last_permit:
#                 response = {
#                     "start_location_name": last_permit.end_location_name,
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


