from django.urls import include, path
from rest_framework.routers import DefaultRouter

from notification.views import AdminAuditLogViewSet

router = DefaultRouter()
router.register(r"admin/audit-logs", AdminAuditLogViewSet, basename="admin-audit-logs")

urlpatterns = [
    path("", include(router.urls)),
]
