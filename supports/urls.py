from django.urls import path, include
from rest_framework.routers import DefaultRouter
from supports.views import (
    SupportTicketViewSet,
    TicketStatsView,
    TicketArchiveView,
    TicketAssignView,
    TicketCloneView,
    TicketMessagesView,
    TicketAttachmentsView,
    TicketAttachmentDownloadView,
    TicketRelatedView,
    TicketDraftListView,
    AssigneeListView,
    CustomerSearchView,
    WebsiteTicketCreateView,
    TeamContactInfoView,
    TeamTopicsDictionaryView,
    TeamTicketPrefillView,
    TeamSubmitTicketView,
    TeamMyTicketsListView,
    TeamSupportResourcesListView,
    TeamSupportResourceDownloadView,
    AdminSupportResourceViewSet,
)

router = DefaultRouter()
router.register(r"tickets", SupportTicketViewSet, basename="support-tickets")
router.register(r"admin/resources", AdminSupportResourceViewSet, basename="admin-support-resources")

urlpatterns = [
    # ── Team Dashboard Support Endpoints ─────────────────────────────────────
    path("team/contact-info/", TeamContactInfoView.as_view(), name="team-support-contact-info"),
    path("team/topics/", TeamTopicsDictionaryView.as_view(), name="team-support-topics"),
    path("team/prefill/", TeamTicketPrefillView.as_view(), name="team-support-prefill"),
    path("team/submit-ticket/", TeamSubmitTicketView.as_view(), name="team-support-submit-ticket"),
    path("team/my-tickets/", TeamMyTicketsListView.as_view(), name="team-support-my-tickets"),
    path("team/resources/", TeamSupportResourcesListView.as_view(), name="team-support-resources"),
    path("team/resources/<int:resource_id>/download/", TeamSupportResourceDownloadView.as_view(), name="team-support-resource-download"),

    # ── Admin Dashboard Support Endpoints ─────────────────────────────────────
    path("tickets/stats/", TicketStatsView.as_view(), name="ticket-stats"),
    path("tickets/drafts/", TicketDraftListView.as_view(), name="ticket-drafts"),
    path("assignees/", AssigneeListView.as_view(), name="support-assignees"),
    path("customers/search/", CustomerSearchView.as_view(), name="support-customer-search"),

    # ── Website Integration (WPForms Webhook) ─────────────────────────────────
    path("website/submit", WebsiteTicketCreateView.as_view(), name="support-website-webhook"),

    # ── Per-ticket actions (Admin) ────────────────────────────────────────────
    path("tickets/<int:pk>/archive/", TicketArchiveView.as_view(), name="ticket-archive"),
    path("tickets/<int:pk>/assign/", TicketAssignView.as_view(), name="ticket-assign"),
    path("tickets/<int:pk>/clone/", TicketCloneView.as_view(), name="ticket-clone"),
    path("tickets/<int:pk>/messages/", TicketMessagesView.as_view(), name="ticket-messages"),
    path("tickets/<int:pk>/attachments/", TicketAttachmentsView.as_view(), name="ticket-attachments"),
    path("tickets/<int:pk>/related/", TicketRelatedView.as_view(), name="ticket-related"),
    path("tickets/attachments/<int:pk>/download/", TicketAttachmentDownloadView.as_view(), name="ticket-attachment-download"),

    # ── Router endpoints (tickets CRUD, admin resources CRUD) ─────────────────
    path("", include(router.urls)),
]

