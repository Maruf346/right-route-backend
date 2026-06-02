from django.shortcuts import render
from core.permissions import IsAdminUserPermission
from rest_framework.permissions import IsAuthenticated
from core.viewsets import OwnModelViewSet
from .models import SubscriptionPlan
from .serializers import SubscriptionPlanSerializer


class SubscriptionPlanViewSet(OwnModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsAdminUserPermission]
    queryset = SubscriptionPlan.objects.all().order_by("-created_at")
    model = SubscriptionPlan
    delete_message = "Subscription Plan Deleted."


