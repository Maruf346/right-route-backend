
from rest_framework import status, exceptions
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from django.db import transaction
from subscription.models import SubscriptionPlan

class OwnModelViewSet(ModelViewSet):
    delete_message = "Object Deleted."
    model = SubscriptionPlan
    
    # ******* GET/Retrieve Perform *******
    def perform_retrieve(self, serializer):
        return Response(
            {
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_200_OK
        )
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return self.perform_retrieve(serializer)
    
    # ******* GET/List Perform *******
    def list_success_response(self, serializer):
        return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "data": serializer.data
                }, status=status.HTTP_200_OK
            )
    
    def list(self, request, *args, **kwargs):
        try:
            # queryset = self.filter_queryset(self.get_queryset())
            # page = self.paginate_queryset(queryset)
            # if page is not None:
            #     serializer = self.get_serializer(page, many=True)
            #     return self.get_paginated_response(serializer.data)

            # serializer = self.get_serializer(queryset, many=True)
            # return Response(serializer.data)
            
            response = super().list(request, *args, **kwargs)
            return self.list_success_response(response)
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ******* Post/Create Perform *******
    def create_success_response(self, serializer):
        serializer.save()
        return Response(
            {
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_201_CREATED
        )
    
    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                return self.create_success_response(serializer)
        except exceptions.ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error,
                },status=status.HTTP_400_BAD_REQUEST
            )
        except exceptions.PermissionDenied as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_400_BAD_REQUEST
            )
    
    #  ******* Patch or Put/Update Perform *******
    def update_success_response(self, serializer):
        serializer.save()
        return Response(
            {
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_200_OK
        )
    
    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                object = self.get_object()
                serializer = self.get_serializer(object, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                return self.update_success_response(serializer)
        except exceptions.ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error,
                },status=status.HTTP_400_BAD_REQUEST
            )
        except exceptions.PermissionDenied as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_400_BAD_REQUEST
            )
    
    #  ******* Delete/Destroy Perform *******
    def destroy(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                instance = self.get_object()
                instance.delete()
                return Response(
                    {
                        "success": True,
                        "detail": self.delete_message,
                    }, status=status.HTTP_200_OK
                )
        except self.model.DoesNotExist as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_404_NOT_FOUND
            )
        except exceptions.PermissionDenied as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_400_BAD_REQUEST
            )

class OwnReadOnlyModelViewSet(ReadOnlyModelViewSet):
    # ******* GET/Retrieve Perform *******
    def perform_retrieve(self, serializer):
        return Response(
            {
                "success": True,
                "data": serializer.data
            }, status=status.HTTP_200_OK
        )
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return self.perform_retrieve(serializer)
    
    
    # ******* GET/List Perform *******
    def list_success_response(self, serializer):
        return Response(
                {
                    "success": True,
                    "count": len(serializer.data),
                    "data": serializer.data
                }, status=status.HTTP_200_OK
            )
    
    def list(self, request, *args, **kwargs):
        try:
            # queryset = self.filter_queryset(self.get_queryset())
            # page = self.paginate_queryset(queryset)
            # if page is not None:
            #     serializer = self.get_serializer(page, many=True)
            #     return self.get_paginated_response(serializer.data)

            # serializer = self.get_serializer(queryset, many=True)
            # return Response(serializer.data)
            
            response = super().list(request, *args, **kwargs)
            return self.list_success_response(response)
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e),
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


