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
from account.models import User, AdminUserProfile, Team
from team_dashboard.permissions import (
    IsTeamDashboardUser,
    HasTeamDashboardPermission,
    get_team_for_user,
)
from supports.constants import (
    MainCategory,
    TicketPriority,
    TicketSource,
    TicketStatus,
    PlanType,
    SUPPORT_CONTACT_PHONE,
    SUPPORT_CONTACT_EMAILS,
    SUBCATEGORIES,
    CATEGORY_ABBREVIATIONS,
)
from supports.models import (
    SupportTicket,
    TicketAttachment,
    TicketMessage,
    TicketActivityLog,
    SupportResource,
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
    TeamContactInfoSerializer,
    TeamTopicsDictionarySerializer,
    TeamTicketPrefillSerializer,
    TeamSubmitTicketSerializer,
    SupportResourceSerializer,
    SupportResourceAdminCreateUpdateSerializer,
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
        tags=["Support - Admin"],
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
        tags=["Support - Admin"],
        summary="Get full support ticket details",
    ),
    create=extend_schema(
        tags=["Support - Admin"],
        summary="Create a new support ticket or draft from Admin Dashboard",
    ),
    update=extend_schema(
        tags=["Support - Admin"],
        summary="Update ticket status, priority, assignment, etc.",
    ),
    partial_update=extend_schema(
        tags=["Support - Admin"],
        summary="Update ticket status, priority, assignment, etc.",
    ),
    destroy=extend_schema(
        tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Admin"],
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
    tags=["Support - Public / Webhook"],
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


# ==============================================================================
# ── TEAM DASHBOARD SUPPORT VIEWS ─────────────────────────────────────────────
# ==============================================================================


@extend_schema(
    tags=["Support - Team"],
    summary="Get RightRoute support contact information",
    description="Returns support phone numbers and dedicated department emails (Technical, Subscription, Fleet, Legal).",
    responses={200: TeamContactInfoSerializer},
)
class TeamContactInfoView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.contact_support"

    def get(self, request):
        data = {
            "phone": SUPPORT_CONTACT_PHONE,
            "emails": {
                "technical_issues": SUPPORT_CONTACT_EMAILS["technical_issues"],
                "subscription_help": SUPPORT_CONTACT_EMAILS["subscription_help"],
                "fleet_sales": SUPPORT_CONTACT_EMAILS["fleet_sales"],
                "legal": SUPPORT_CONTACT_EMAILS["legal"],
            },
        }
        return Response(data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Support - Team"],
    summary="Get support ticket topic categories and subtopics dictionary",
    description="Returns all 10 main categories and their nested subtopics for the Submit Ticket form.",
    responses={200: TeamTopicsDictionarySerializer},
)
class TeamTopicsDictionaryView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.submit_ticket"

    def get(self, request):
        topic_list = []
        for choice in MainCategory.choices:
            key = choice[0]
            label = choice[1]
            subtopics = SUBCATEGORIES.get(key, [])
            abbrev = CATEGORY_ABBREVIATIONS.get(key, label)
            topic_list.append({
                "key": key,
                "label": label,
                "abbrev": abbrev,
                "subtopics": subtopics,
            })
        return Response({"topics": topic_list}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Support - Team"],
    summary="Get pre-fill customer information for support ticket form",
    description="Auto-populates customer name, email, phone, company name, and plan type from logged in team session.",
    responses={200: TeamTicketPrefillSerializer},
)
class TeamTicketPrefillView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.submit_ticket"

    def get(self, request):
        user = request.user
        team = get_team_for_user(user)

        name = ""
        phone = ""
        if hasattr(user, "team_admin_profile") and user.team_admin_profile.full_name:
            name = user.team_admin_profile.full_name
            phone = user.team_admin_profile.phone_number or ""
        elif hasattr(user, "team_member_profile") and user.team_member_profile.username:
            name = user.team_member_profile.username
        else:
            name = user.email.split("@")[0]

        company = team.name if team else ""
        plan_type = "Team"

        data = {
            "name": name,
            "account_email": user.email,
            "phone": phone,
            "company": company,
            "plan_type": plan_type,
        }
        return Response(data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Support - Team"],
    summary="Submit a support ticket from Team Dashboard",
    description="Creates a support ticket with up to 3 attachments, assigns ticket number, and notifies staff and customer.",
    request=TeamSubmitTicketSerializer,
    responses={
        201: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "ticket_id": {"type": "integer"},
                "ticket_number": {"type": "string"},
                "status": {"type": "string"},
                "priority": {"type": "string"},
                "created_at": {"type": "string"},
            },
        }
    },
)
class TeamSubmitTicketView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.submit_ticket"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = TeamSubmitTicketSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save()

        return Response(
            {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.get_status_display(),
                "priority": ticket.get_priority_display(),
                "created_at": ticket.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Support - Team"],
    summary="List tickets submitted by current team or user",
    parameters=[
        OpenApiParameter("search", OpenApiTypes.STR, description="Search query"),
        OpenApiParameter("status", OpenApiTypes.STR, description="Filter by status"),
        OpenApiParameter("page", OpenApiTypes.INT, description="Page number"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="Page size"),
    ],
    responses={200: SupportTicketListSerializer(many=True)},
)
class TeamMyTicketsListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.submit_ticket"

    def get(self, request):
        team = get_team_for_user(request.user)
        qs = SupportTicket.objects.filter(
            Q(team=team) | Q(customer_user=request.user) | Q(account_email__iexact=request.user.email)
        ).select_related("assigned_to", "customer_user").order_by("-created_at")

        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            qs = qs.filter(
                Q(ticket_number__icontains=search)
                | Q(subject__icontains=search)
                | Q(description__icontains=search)
            )

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = SupportTicketListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = SupportTicketListSerializer(qs, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Support - Team"],
    summary="List downloadable support resources and guides",
    parameters=[
        OpenApiParameter("search", OpenApiTypes.STR, description="Search query by file title or description"),
        OpenApiParameter("category", OpenApiTypes.STR, description="Filter by resource category"),
    ],
    responses={200: SupportResourceSerializer(many=True)},
)
class TeamSupportResourcesListView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.resources"

    def get(self, request):
        qs = SupportResource.objects.filter(is_active=True).order_by("title")

        search = request.query_params.get("search") or request.query_params.get("q")
        if search:
            search = search.strip()
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(file_name__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category__iexact=category)

        serializer = SupportResourceSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Support - Team"],
    summary="Download a support resource file",
    description="Streams the file attachment and increments the resource download counter.",
)
class TeamSupportResourceDownloadView(APIView):
    permission_classes = [IsAuthenticated, IsTeamDashboardUser, HasTeamDashboardPermission]
    required_team_permission = "support.resources"

    def get(self, request, resource_id):
        resource = get_object_or_404(SupportResource, id=resource_id, is_active=True)
        if not resource.file:
            raise Http404("Resource file not found on disk.")

        # Increment download counter
        resource.download_count += 1
        resource.save(update_fields=["download_count", "updated_at"])

        response = FileResponse(
            resource.file.open("rb"),
            as_attachment=True,
            filename=resource.file_name or os.path.basename(resource.file.name),
        )
        return response


# ==============================================================================
# ── ADMIN SUPPORT RESOURCE VIEWS ─────────────────────────────────────────────
# ==============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: List all support resources (active and inactive)",
    ),
    retrieve=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: Get support resource details",
    ),
    create=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: Upload and create a new support resource (guide, template, video)",
    ),
    update=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: Update support resource title, category, or file",
    ),
    partial_update=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: Partially update support resource",
    ),
    destroy=extend_schema(
        tags=["Support - Admin"],
        summary="Admin: Delete a support resource",
    ),
)
class AdminSupportResourceViewSet(viewsets.ModelViewSet):
    queryset = SupportResource.objects.all().order_by("-created_at")
    permission_classes = [IsAuthenticated, HasAdminDashboardPermission]
    required_admin_permission = "support_tools.support_tickets"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return SupportResourceAdminCreateUpdateSerializer
        return SupportResourceSerializer

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)

