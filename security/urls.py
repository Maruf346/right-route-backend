from django.urls import path, include
from rest_framework.routers import DefaultRouter

from security.views import (
    DataProtectionRequestViewSet,
    ExportDownloadView,
    FindCustomerView,
    GenerateRequestIdView,
)

router = DefaultRouter()
router.register(
    r"security/data-protection",
    DataProtectionRequestViewSet,
    basename="security-data-protection",
)

urlpatterns = [
    # ViewSet routes (list, create, retrieve, partial_update + custom actions)
    path("", include(router.urls)),

    # Standalone endpoints
    path(
        "security/data-protection/generate-id/",
        GenerateRequestIdView.as_view(),
        name="security-generate-request-id",
    ),
    path(
        "security/data-protection/find-customer/",
        FindCustomerView.as_view(),
        name="security-find-customer",
    ),

    # Secure download — no auth required, protected by token
    path(
        "security/data-protection/download/<str:token>/",
        ExportDownloadView.as_view(),
        name="security-export-download",
    ),
]
