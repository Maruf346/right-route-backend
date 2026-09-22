from django.urls import path, include
from rest_framework.routers import DefaultRouter

from security.views import (
    DataProtectionRequestViewSet,
    ExportDownloadView,
    FindCustomerView,
    GenerateRequestIdView,
    TeamDataProtectionPrefillView,
    TeamDataProtectionOptionsView,
    TeamDataProtectionSubmitView,
    TeamDataProtectionMyRequestsListView,
    TeamDeleteAccountInfoView,
)

router = DefaultRouter()
router.register(
    r"security/data-protection",
    DataProtectionRequestViewSet,
    basename="security-data-protection",
)

urlpatterns = [
    # ── Team Dashboard Endpoints ─────────────────────────────────────────────
    path(
        "security/team/data-protection/prefill/",
        TeamDataProtectionPrefillView.as_view(),
        name="team-data-protection-prefill",
    ),
    path(
        "security/team/data-protection/options/",
        TeamDataProtectionOptionsView.as_view(),
        name="team-data-protection-options",
    ),
    path(
        "security/team/data-protection/submit/",
        TeamDataProtectionSubmitView.as_view(),
        name="team-data-protection-submit",
    ),
    path(
        "security/team/data-protection/my-requests/",
        TeamDataProtectionMyRequestsListView.as_view(),
        name="team-data-protection-my-requests",
    ),
    path(
        "security/team/delete-account/info/",
        TeamDeleteAccountInfoView.as_view(),
        name="team-delete-account-info",
    ),

    # ── Admin Dashboard Endpoints (ViewSet + Helpers) ────────────────────────
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

    # Secure download — token based
    path(
        "security/data-protection/download/<str:token>/",
        ExportDownloadView.as_view(),
        name="security-export-download",
    ),

    # ViewSet routes
    path("", include(router.urls)),
]

