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
)

router = DefaultRouter()
router.register(r"tickets", SupportTicketViewSet, basename="support-tickets")

urlpatterns = [
    # Top metrics / list helpers (before <pk> paths)
    path("tickets/stats/", TicketStatsView.as_view(), name="ticket-stats"),
    path("tickets/drafts/", TicketDraftListView.as_view(), name="ticket-drafts"),
    path("assignees/", AssigneeListView.as_view(), name="support-assignees"),
    path("customers/search/", CustomerSearchView.as_view(), name="support-customer-search"),

    # Website integration
    path("website/submit", WebsiteTicketCreateView.as_view(), name="support-website-webhook"),

    # Per-ticket actions
    path("tickets/<int:pk>/archive/", TicketArchiveView.as_view(), name="ticket-archive"),
    path("tickets/<int:pk>/assign/", TicketAssignView.as_view(), name="ticket-assign"),
    path("tickets/<int:pk>/clone/", TicketCloneView.as_view(), name="ticket-clone"),
    path("tickets/<int:pk>/messages/", TicketMessagesView.as_view(), name="ticket-messages"),
    path("tickets/<int:pk>/attachments/", TicketAttachmentsView.as_view(), name="ticket-attachments"),
    path("tickets/<int:pk>/related/", TicketRelatedView.as_view(), name="ticket-related"),
    path("tickets/attachments/<int:pk>/download/", TicketAttachmentDownloadView.as_view(), name="ticket-attachment-download"),

    # Router endpoints (tickets list, retrieve, create, update, delete)
    path("", include(router.urls)),
]
