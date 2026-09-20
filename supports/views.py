import os
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.http import FileResponse, Http404
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes

from core.permissions import HasAdminDashboardPermission
from account.models import User, AdminUserProfile
from supports.constants import (
    MainCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
    PlanType,
)
from supports.models import (
    SupportTicket,
    TicketAttachment,
    TicketMessage,
    TicketActivityLog,
)
from supports.serializers import (
    SupportTicketListSerializer,
    SupportTicketDetailSerializer,
    SupportTicketCreateSerializer,
    SupportTicketUpdateSerializer,
    WebsiteTicketCreateSerializer,
    TicketMessageSerializer,
    TicketAttachmentSerializer,
    TicketStatsSerializer,
    AssigneeOptionSerializer,
    CustomerSearchResultSerializer,
    RelatedTicketSerializer,
)
from supports.utils import (
    generate_ticket_number,
    match_customer_account,
    scan_file_for_malware,
)
from supports.emails import (
    send_customer_response_email,
    send_assignment_email,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        tags=["Support - Tickets"],
        summary="List support tickets (Live or Archived)",
        parameters=[
            OpenApiParameter("scope", OpenApiTypes.STR, description="Filter scope: 'live' (default), 'archived', or 'draft'"),
            OpenApiParameter("main_category", OpenApiTypes.STR, description="Filter by MainCategory key"),
            OpenApiParameter("subcategory", OpenApiTypes.STR, description="Filter by subcategory string"),
            OpenApiParameter("priority", OpenApiTypes.STR, description="Filter by TicketPriority (LOW, NORMAL, HIGH, URGENT)"),
            OpenApiParameter("plan_type", OpenApiTypes.STR, description="Filter by plan type (Individual, Team, Fleet, Trial User)"),
            OpenApiParameter("assigned_to", OpenApiTypes.INT, description="Filter by assigned admin user ID"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Search term across ticket number, customer name, email, subject"),
        ],
    ),
    retrieve=extend_schema(
        tags=["Support - Tickets"],
        summary="Get full support ticket details",
    ),
    create=extend_schema(
        tags=["Support - Tickets"],
        summary="Create a new support ticket or draft from Admin Dashboard",
    ),
    partial_update=extend_schema(
        tags=["Support - Tickets"],
        summary="Update ticket status, priority, assignment, etc.",
    ),
    destroy=extend_schema(
        tags=["Support - Tickets"],
        summary="Permanently delete a support ticket",
    ),
)
class SupportTicketViewSet(viewsets.ModelViewSet):
    queryset = SupportTicket.objects.all().select_related("assigned_to", "customer_user", "created_by")
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == "list":
            return SupportTicketListSerializer
        elif self.action == "retrieve":
            return SupportTicketDetailSerializer
        elif self.action == "create":
            return SupportTicketCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return SupportTicketUpdateSerializer
        return SupportTicketDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        scope = self.request.query_params.get("scope", "live").lower()

        if scope == "archived":
            qs = qs.filter(Q(archived_at__isnull=False) | Q(status=TicketStatus.CLOSED))
        elif scope == "draft":
            qs = qs.filter(status=TicketStatus.DRAFT)
        else:  # live tickets
            qs = qs.filter(archived_at__isnull=True).exclude(status__in=[TicketStatus.CLOSED, TicketStatus.DRAFT])

        # Filters
        main_cat = self.request.query_params.get("main_category") or self.request.query_params.get("category")
        if main_cat:
            qs = qs.filter(main_category__iexact=main_cat)

        subcat = self.request.query_params.get("subcategory")
        if subcat:
            qs = qs.filter(subcategory__icontains=subcat)

        prio = self.request.query_params.get("priority")
        if prio:
            qs = qs.filter(priority__iexact=prio)

        plan = self.request.query_params.get("plan_type")
        if plan:
            qs = qs.filter(plan_type__iexact=plan)

        assigned = self.request.query_params.get("assigned_to")
        if assigned:
            if assigned.isdigit():
                qs = qs.filter(assigned_to_id=int(assigned))
            else:
                qs = qs.filter(Q(assigned_name__icontains=assigned) | Q(assigned_to__admin_profile__full_name__icontains=assigned))

        search = self.request.query_params.get("search")
        if search:
            s = search.strip()
            qs = qs.filter(
                Q(ticket_number__icontains=s)
                | Q(customer_name__icontains=s)
                | Q(customer_email__icontains=s)
                | Q(subject__icontains=s)
                | Q(description__icontains=s)
            )

        return qs.order_by("-created_at")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.refresh_auto_status()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Get count of Live and Archived support tickets",
    responses={200: TicketStatsSerializer},
)
class TicketStatsView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request):
        live_count = SupportTicket.objects.filter(
            archived_at__isnull=True
        ).exclude(status__in=[TicketStatus.CLOSED, TicketStatus.DRAFT]).count()

        archived_count = SupportTicket.objects.filter(
            Q(archived_at__isnull=False) | Q(status=TicketStatus.CLOSED)
        ).count()

        return Response({
            "live_tickets_count": live_count,
            "archived_tickets_count": archived_count,
        })


@extend_schema(
    tags=["Support - Tickets"],
    summary="Archive a support ticket (moves to archive and sets status=Closed)",
    responses={200: SupportTicketDetailSerializer},
)
class TicketArchiveView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        ticket.archived_at = timezone.now()
        ticket.status = TicketStatus.CLOSED
        ticket.updated_by = request.user
        ticket.save()

        TicketActivityLog.objects.create(
            ticket=ticket,
            action_summary="Ticket moved to Archives and marked Closed",
            performed_by=request.user,
        )
        return Response(SupportTicketDetailSerializer(ticket).data)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Assign a support ticket to an admin agent",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "assigned_to_id": {"type": "integer"},
                "assigned_name": {"type": "string"},
            },
        }
    },
    responses={200: SupportTicketDetailSerializer},
)
class TicketAssignView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        assigned_to_id = request.data.get("assigned_to_id")
        assigned_name = request.data.get("assigned_name")

        assignee_user = None
        if assigned_to_id:
            assignee_user = get_object_or_404(User, pk=assigned_to_id)
            if not assigned_name and hasattr(assignee_user, "admin_profile"):
                assigned_name = assignee_user.admin_profile.full_name

        ticket.assigned_to = assignee_user
        ticket.assigned_name = assigned_name or (assignee_user.email if assignee_user else None)
        ticket.updated_by = request.user
        ticket.save()

        TicketActivityLog.objects.create(
            ticket=ticket,
            action_summary=f"Ticket assigned to {ticket.assigned_name or 'Unassigned'}",
            performed_by=request.user,
        )

        if assignee_user:
            send_assignment_email(ticket, assignee_user, ticket.assigned_name)

        return Response(SupportTicketDetailSerializer(ticket).data)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Clone an archived ticket into a new ticket draft or live ticket",
    responses={201: SupportTicketDetailSerializer},
)
class TicketCloneView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def post(self, request, pk):
        source_ticket = get_object_or_404(SupportTicket, pk=pk)

        new_ticket = SupportTicket.objects.create(
            ticket_number=generate_ticket_number(),
            status=TicketStatus.NEW,
            priority=source_ticket.priority,
            source=TicketSource.DASHBOARD,
            customer_name=source_ticket.customer_name,
            customer_email=source_ticket.customer_email,
            customer_phone=source_ticket.customer_phone,
            company_name=source_ticket.company_name,
            account_email=source_ticket.account_email,
            customer_user=source_ticket.customer_user,
            plan_type=source_ticket.plan_type,
            main_category=source_ticket.main_category,
            subcategory=source_ticket.subcategory,
            subject=f"Copy: {source_ticket.subject}",
            description=source_ticket.description,
            safety_critical=source_ticket.safety_critical,
            platform=source_ticket.platform,
            device=source_ticket.device,
            app_version=source_ticket.app_version,
            preferred_contact_method=source_ticket.preferred_contact_method,
            created_by=request.user,
            updated_by=request.user,
        )

        TicketActivityLog.objects.create(
            ticket=new_ticket,
            action_summary=f"Cloned from ticket {source_ticket.ticket_number}",
            performed_by=request.user,
        )

        return Response(SupportTicketDetailSerializer(new_ticket).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Add a message or internal note to a ticket thread",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "is_internal_note": {"type": "boolean", "default": False},
            },
            "required": ["body"],
        }
    },
    responses={201: TicketMessageSerializer},
)
class TicketMessagesView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        body = request.data.get("body", "").strip()
        is_internal_note = request.data.get("is_internal_note", False)

        if not body:
            return Response({"detail": "Message body cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)

        sender_name = getattr(getattr(request.user, "admin_profile", None), "full_name", None) or request.user.email

        message = TicketMessage.objects.create(
            ticket=ticket,
            body=body,
            is_internal_note=is_internal_note,
            sent_by=request.user,
            sender_name=sender_name,
        )

        # Update ticket status if response sent to customer
        if not is_internal_note:
            ticket.status = TicketStatus.WAITING_CUSTOMER
            ticket.save(update_fields=["status", "updated_at"])
            send_customer_response_email(ticket, body)

        TicketActivityLog.objects.create(
            ticket=ticket,
            action_summary=f"Added {'internal note' if is_internal_note else 'response to customer'}",
            performed_by=request.user,
        )

        return Response(TicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Upload an attachment to a ticket",
    responses={201: TicketAttachmentSerializer},
)
class TicketAttachmentsView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TicketAttachmentSerializer(data={"file": file_obj})
        serializer.is_valid(raise_exception=True)

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            file=file_obj,
            original_filename=file_obj.name,
            file_size=file_obj.size,
            file_type=os.path.splitext(file_obj.name)[1].lstrip(".").lower(),
            uploaded_by=request.user,
        )

        TicketActivityLog.objects.create(
            ticket=ticket,
            action_summary=f"Uploaded attachment: {file_obj.name}",
            performed_by=request.user,
        )

        return Response(TicketAttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Download an attachment safely",
)
class TicketAttachmentDownloadView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request, pk):
        attachment = get_object_or_404(TicketAttachment, pk=pk)
        if not attachment.file or not os.path.exists(attachment.file.path):
            raise Http404("File not found on server.")

        response = FileResponse(open(attachment.file.path, "rb"), as_attachment=True, filename=attachment.original_filename)
        return response


@extend_schema(
    tags=["Support - Tickets"],
    summary="Get related open tickets",
    responses={200: RelatedTicketSerializer(many=True)},
)
class TicketRelatedView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        first_word = (ticket.subject.split()[0] if ticket.subject else "")
        qs = (
            SupportTicket.objects.filter(main_category=ticket.main_category)
            .exclude(id=ticket.id)
            .exclude(status__in=[TicketStatus.CLOSED, TicketStatus.DRAFT])
            .exclude(archived_at__isnull=False)
        )
        if first_word and len(first_word) > 2:
            qs = qs.filter(subject__icontains=first_word)
        
        serializer = RelatedTicketSerializer(qs[:5], many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Get list of all draft tickets",
    responses={200: SupportTicketListSerializer(many=True)},
)
class TicketDraftListView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request):
        drafts = SupportTicket.objects.filter(status=TicketStatus.DRAFT).order_by("-created_at")
        serializer = SupportTicketListSerializer(drafts, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Get list of admin users for assignee dropdown",
    responses={200: AssigneeOptionSerializer(many=True)},
)
class AssigneeListView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request):
        profiles = AdminUserProfile.objects.select_related("user").all()
        results = []
        for p in profiles:
            results.append({
                "id": p.user.id,
                "email": p.user.email,
                "full_name": p.full_name or p.user.email,
            })
        return Response(results)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Search customer accounts to auto-fill Create Ticket form",
    parameters=[
        OpenApiParameter("q", OpenApiTypes.STR, description="Search query by name or email"),
    ],
    responses={200: CustomerSearchResultSerializer(many=True)},
)
class CustomerSearchView(APIView):
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query or len(query) < 2:
            return Response([])

        users = (
            User.objects.filter(
                Q(email__icontains=query)
                | Q(admin_profile__full_name__icontains=query),
                is_staff=False,
            )
            .distinct()[:10]
        )

        results = []
        for u in users:
            _, plan_name, is_active = match_customer_account(u.email)
            full_name = getattr(getattr(u, "admin_profile", None), "full_name", "")
            results.append({
                "id": u.id,
                "email": u.email,
                "full_name": full_name,
                "phone": getattr(getattr(u, "admin_profile", None), "phone", None),
                "company_name": getattr(getattr(u, "owned_team", None), "name", None),
                "plan_type": plan_name,
                "is_active": is_active,
            })
        return Response(results)


@extend_schema(
    tags=["Support - Tickets"],
    summary="Public endpoint: Create support ticket from Website WPForms",
    request=WebsiteTicketCreateSerializer,
    responses={
        201: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "ticket_id": {"type": "integer"},
                "ticket_number": {"type": "string"},
                "status": {"type": "string"},
            },
        }
    },
)
class WebsiteTicketCreateView(APIView):
    """
    Public API endpoint called by WPForms webhook on getrightroute.app.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = WebsiteTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save()

        return Response(
            {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.get_status_display(),
            },
            status=status.HTTP_201_CREATED,
        )
