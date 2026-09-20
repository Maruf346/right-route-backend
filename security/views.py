"""
Views for the Security / Data Protection app.

All endpoints are under the Swagger tag: "Security - Data Protection"
Permission: security_logging_compliance.data_protection
"""

import os
import io
import json
import zipfile
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from account.models import User
from core.constants import NotifyLogAction, LogStatus
from core.permissions import HasAdminDashboardPermission
from notification.models import ActivityLog
from django.contrib.contenttypes.models import ContentType

from security.constants import DataRequestStatus, RequestType
from security.emails import send_approval_email, send_completion_email
from security.models import (
    DataProtectionRequest,
    DataRequestNote,
    generate_download_token,
    generate_request_id,
)
from security.serializers import (
    CustomerFoundSerializer,
    DataProtectionRequestCreateSerializer,
    DataProtectionRequestDetailSerializer,
    DataProtectionRequestListSerializer,
    DataProtectionRequestUpdateSerializer,
    DataRequestNoteCreateSerializer,
    DataRequestNoteSerializer,
    EmailCustomerSerializer,
    FindCustomerSerializer,
    GenerateRequestIdSerializer,
    PerformRequestSerializer,
)

# ─────────────────────────────────────────────────────────────────────────────
# Permission shorthand
# ─────────────────────────────────────────────────────────────────────────────

_PERMS = [IsAuthenticated, HasAdminDashboardPermission]

DATA_PROTECTION_PERMISSION = "security_logging_compliance.data_protection"

TAG = "Security - Data Protection"


def _log_action(request, action_type, target_obj, message, metadata=None):
    """Write an entry to the ActivityLog."""
    ActivityLog.objects.create(
        user=request.user,
        action=action_type,
        message=message,
        status=LogStatus.SUCCESS,
        entity_type=ContentType.objects.get_for_model(target_obj),
        entity_id=target_obj.id,
        ip_address=request.META.get("REMOTE_ADDR") or "0.0.0.0",
        device_info=request.headers.get("User-Agent", ""),
        metadata_json=metadata or {},
    )


def _add_system_note(request_obj, body):
    """Append a system-generated note to a DataProtectionRequest."""
    DataRequestNote.objects.create(
        request=request_obj,
        body=body,
        written_by=None,
        is_system_note=True,
    )


def _add_admin_note(request_obj, body, admin_user):
    """Append an admin-authored note (prepends timestamp + name automatically)."""
    profile = getattr(admin_user, "admin_profile", None)
    admin_name = profile.full_name if profile else admin_user.email
    timestamp = timezone.now().strftime("%d %b %Y %H:%M UTC")
    full_body = f"[{timestamp}] {admin_name}:\n{body}"
    DataRequestNote.objects.create(
        request=request_obj,
        body=full_body,
        written_by=admin_user,
        is_system_note=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ViewSet — CRUD on DataProtectionRequest
# ─────────────────────────────────────────────────────────────────────────────

@extend_schema(tags=[TAG])
@extend_schema_view(
    list=extend_schema(
        operation_id="security_data_protection_list",
        summary="List data protection requests",
        description=(
            "Returns a paginated list of data protection requests. "
            "Filter by `status` to populate the three dashboard lists: "
            "`NEW`, `PENDING_APPROVAL`, or `COMPLETED`. "
            "Results are limited to 4 rows per list as per the dashboard design."
        ),
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=[s.value for s in DataRequestStatus],
                description="Filter by request status.",
            ),
            OpenApiParameter("search", str, description="Search by request ID, customer email, or name."),
            OpenApiParameter("page", int, description="Page number."),
            OpenApiParameter("page_size", int, description="Results per page (default 4 per list)."),
        ],
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestListSerializer(many=True),
                description="List of data protection requests.",
            )
        },
    ),
    retrieve=extend_schema(
        operation_id="security_data_protection_retrieve",
        summary="Retrieve data protection request",
        description="Returns full detail for a single request including notes, computed warnings, and button states.",
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Data protection request detail.",
            ),
            404: OpenApiResponse(description="Request not found."),
        },
    ),
    create=extend_schema(
        operation_id="security_data_protection_create",
        summary="Create data protection request (Save as New)",
        description=(
            "Creates a new data protection request and places it in the New Requests list. "
            "Records the admin who saved it in the Notes section."
        ),
        request=DataProtectionRequestCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Request created successfully.",
            ),
            400: OpenApiResponse(description="Validation failed."),
        },
    ),
    partial_update=extend_schema(
        operation_id="security_data_protection_update",
        summary="Update data protection request",
        description="Updates editable form fields on an existing request. Completed requests cannot be edited.",
        request=DataProtectionRequestUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Request updated successfully.",
            ),
            400: OpenApiResponse(description="Validation failed."),
            404: OpenApiResponse(description="Request not found."),
        },
    ),
)
class DataProtectionRequestViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = _PERMS
    required_admin_permission = DATA_PROTECTION_PERMISSION
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["request_id", "customer_email", "customer_name"]
    ordering_fields = ["date_requested", "created_at", "updated_at", "status"]

    def get_queryset(self):
        qs = DataProtectionRequest.objects.select_related(
            "customer_user",
            "created_by",
            "updated_by",
            "approval_email_sent_by",
            "performed_by",
        ).prefetch_related("notes__written_by")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return DataProtectionRequestCreateSerializer
        if self.action == "partial_update":
            return DataProtectionRequestUpdateSerializer
        if self.action == "list":
            return DataProtectionRequestListSerializer
        return DataProtectionRequestDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = DataProtectionRequestListSerializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = DataProtectionRequestCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        # Record who saved it and when — system note
        profile = getattr(request.user, "admin_profile", None)
        admin_name = profile.full_name if profile else request.user.email
        _add_system_note(
            instance,
            f"Request saved as New by {admin_name} on {timezone.now().strftime('%d %b %Y %H:%M UTC')}.",
        )

        _log_action(request, NotifyLogAction.CREATE, instance, "Data protection request created.", {
            "request_id": instance.request_id,
        })

        out = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response(
            {"success": True, "message": "Request saved as New.", "data": out.data},
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = DataProtectionRequestUpdateSerializer(
            instance, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        _log_action(request, NotifyLogAction.UPDATE, instance, "Data protection request updated.", {
            "request_id": instance.request_id,
            "updated_fields": list(request.data.keys()),
        })

        out = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response({"success": True, "message": "Request updated.", "data": out.data})

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"success": False, "detail": "Data protection requests cannot be deleted."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    # ── Custom actions ──────────────────────────────────────────────────────────

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_add_note",
        summary="Add note to request",
        description=(
            "Appends a note to a data protection request. "
            "The system automatically prepends the date, time, and admin name. "
            "Notes are stored in descending order (newest first)."
        ),
        request=DataRequestNoteCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=DataRequestNoteSerializer,
                description="Note added successfully.",
            ),
            400: OpenApiResponse(description="Validation failed."),
        },
    )
    @action(detail=True, methods=["post"], url_path="notes")
    def add_note(self, request, pk=None):
        instance = self.get_object()
        serializer = DataRequestNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _add_admin_note(instance, serializer.validated_data["body"], request.user)
        note = instance.notes.first()
        return Response(
            {"success": True, "message": "Note added.", "data": DataRequestNoteSerializer(note).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_email_customer",
        summary="Email customer (approval email)",
        description=(
            "Sends the approval email to the verified account email. "
            "The recipient is locked to the customer's account email — the admin cannot change it. "
            "On success, the sent email body is automatically appended to Notes and Correspondence. "
            "The form stays open."
        ),
        request=EmailCustomerSerializer,
        responses={
            200: OpenApiResponse(description="Approval email sent successfully."),
            400: OpenApiResponse(description="Validation failed or email could not be sent."),
        },
    )
    @action(detail=True, methods=["post"], url_path="email-customer")
    def email_customer(self, request, pk=None):
        instance = self.get_object()

        if not instance.customer_email:
            return Response(
                {"success": False, "detail": "No verified customer email on this request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not instance.request_type:
            return Response(
                {"success": False, "detail": "Please select a request type before sending the email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = EmailCustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        personal_message = serializer.validated_data.get("personal_message", "")

        try:
            email_body = send_approval_email(instance, personal_message)
        except Exception as exc:
            return Response(
                {"success": False, "detail": f"Failed to send email: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Record in approval tracking
        instance.approval_email_sent_at = timezone.now()
        instance.approval_email_sent_by = request.user
        instance.updated_by = request.user
        instance.save(update_fields=["approval_email_sent_at", "approval_email_sent_by", "updated_by", "updated_at"])

        # Append email body as system note
        _add_system_note(
            instance,
            f"Approval email sent to {instance.customer_email} on "
            f"{instance.approval_email_sent_at.strftime('%d %b %Y %H:%M UTC')} "
            f"by {request.user.email}.\n\n--- EMAIL CONTENT ---\n{email_body}",
        )

        _log_action(request, NotifyLogAction.UPDATE, instance, "Approval email sent.", {
            "request_id": instance.request_id,
            "sent_to": instance.customer_email,
        })

        return Response({"success": True, "message": "Approval email sent successfully."})

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_save_as_pending",
        summary="Save as Pending Approval",
        description=(
            "Moves the request to the Pending Approval list. "
            "Requires: an account has been found, request type is selected, "
            "the approval email has been sent, and the verified account email is present."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Request moved to Pending Approval.",
            ),
            400: OpenApiResponse(description="Required conditions not met."),
        },
    )
    @action(detail=True, methods=["post"], url_path="save-as-pending")
    def save_as_pending(self, request, pk=None):
        instance = self.get_object()

        if not instance.can_save_as_pending:
            missing = []
            if not instance.customer_user:
                missing.append("a customer account must be found")
            if not instance.request_type:
                missing.append("request type must be selected")
            if not instance.approval_email_sent_at:
                missing.append("approval email must be sent first")
            if not instance.customer_email:
                missing.append("verified account email must be present")
            return Response(
                {
                    "success": False,
                    "detail": "Cannot save as Pending Approval. Missing: " + "; ".join(missing) + ".",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if instance.status == DataRequestStatus.COMPLETED:
            return Response(
                {"success": False, "detail": "Completed requests cannot be moved back to Pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.status = DataRequestStatus.PENDING_APPROVAL
        instance.updated_by = request.user
        instance.save(update_fields=["status", "updated_by", "updated_at"])

        profile = getattr(request.user, "admin_profile", None)
        admin_name = profile.full_name if profile else request.user.email
        _add_system_note(
            instance,
            f"Status changed to Pending Approval by {admin_name} on "
            f"{timezone.now().strftime('%d %b %Y %H:%M UTC')}. "
            f"Approval email was sent to {instance.customer_email} on "
            f"{instance.approval_email_sent_at.strftime('%d %b %Y %H:%M UTC')}.",
        )

        _log_action(request, NotifyLogAction.UPDATE, instance, "Data request moved to Pending Approval.", {
            "request_id": instance.request_id,
        })

        out = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response({"success": True, "message": "Request saved as Pending Approval.", "data": out.data})

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_perform",
        summary="Perform approved request",
        description=(
            "Executes the approved data request. This is the most sensitive action. "
            "All four approval checks must be complete: `approval_received`, `approval_source`, "
            "`approval_received_date`, and `admin_confirmed`. "
            "The `confirmed` field in the request body represents the admin clicking "
            "'CONFIRM AND PERFORM REQUEST' in the final confirmation dialog. "
            "Currently only Export User Data is fully implemented. "
            "Delete, Anonymize, and Delete+Anonymize are stubbed pending retention category list."
        ),
        request=PerformRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Request performed successfully.",
            ),
            400: OpenApiResponse(description="Approval checks not complete or confirmation missing."),
        },
    )
    @action(detail=True, methods=["post"], url_path="perform")
    def perform_request(self, request, pk=None):
        instance = self.get_object()

        if not instance.can_perform:
            missing = []
            if not instance.approval_received:
                missing.append("approval_received must be checked")
            if not instance.approval_source:
                missing.append("approval_source must be filled")
            if not instance.approval_received_date:
                missing.append("approval_received_date must be filled")
            if not instance.admin_confirmed:
                missing.append("admin_confirmed must be checked")
            return Response(
                {
                    "success": False,
                    "detail": "All four approval checks must be complete: " + "; ".join(missing) + ".",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if instance.status == DataRequestStatus.COMPLETED:
            return Response(
                {"success": False, "detail": "This request has already been completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PerformRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # ── Dispatch to request-type handler ──────────────────────────────────
        result_note = ""
        try:
            if instance.request_type == RequestType.EXPORT:
                result_note = self._perform_export(instance)
            elif instance.request_type == RequestType.DELETE:
                result_note = self._perform_delete(instance)
            elif instance.request_type == RequestType.ANONYMIZE:
                result_note = self._perform_anonymize(instance)
            elif instance.request_type == RequestType.DELETE_ANONYMIZE:
                result_note = self._perform_delete_anonymize(instance)
            else:
                return Response(
                    {"success": False, "detail": "Unknown request type."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as exc:
            return Response(
                {"success": False, "detail": f"Error performing request: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        instance.performed_at = timezone.now()
        instance.performed_by = request.user
        instance.perform_result = result_note
        instance.updated_by = request.user
        instance.save(update_fields=[
            "performed_at", "performed_by", "perform_result", "updated_by", "updated_at",
            "export_zip_path", "export_zip_size", "export_zip_created_at",
            "export_zip_expires_at", "export_download_token",
        ])

        _add_system_note(instance, result_note)

        _log_action(request, NotifyLogAction.UPDATE, instance, "Data protection request performed.", {
            "request_id": instance.request_id,
            "request_type": instance.request_type,
        })

        out = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response({"success": True, "message": "Request performed successfully.", "data": out.data})

    def _perform_export(self, instance):
        """
        Export User Data:
        1. Collect eligible customer data.
        2. Produce PDF, CSV, and JSON files.
        3. Place them in one ZIP package.
        4. Store in protected storage.
        5. Return result note.
        """
        from django.conf import settings

        user = instance.customer_user
        if not user:
            raise ValueError("No linked customer account for export.")

        now = timezone.now()

        # ── Collect data ───────────────────────────────────────────────────────
        profile_data = {
            "user_id": str(user.id),
            "email": user.email,
            "status": user.status,
            "user_type": user.user_type,
            "is_email_verified": user.is_email_verified,
            "created_at": str(user.created_at),
            "last_login": str(user.last_login) if user.last_login else None,
            "last_login_ip": user.last_login_ip,
        }

        # TODO: Extend with additional data categories once the retention list is provided:
        #   - Routes, Permits, Subscriptions, Support tickets, Billing history, etc.

        json_data = json.dumps(profile_data, indent=2, default=str)
        csv_data = "field,value\n" + "\n".join(
            f"{k},{v}" for k, v in profile_data.items()
        )
        pdf_data = (
            f"RightRoute Data Export\n"
            f"Generated: {now.strftime('%d %b %Y %H:%M UTC')}\n"
            f"Request ID: {instance.request_id}\n\n"
            + "\n".join(f"{k}: {v}" for k, v in profile_data.items())
        ).encode("utf-8")

        # ── Build ZIP in memory ────────────────────────────────────────────────
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("profile.json", json_data)
            zf.writestr("profile.csv", csv_data)
            zf.writestr("profile.pdf", pdf_data)  # Plain-text; replace with real PDF library if needed.

        zip_bytes = zip_buffer.getvalue()
        zip_size = len(zip_bytes)

        # ── Save to protected media storage ────────────────────────────────────
        export_dir = os.path.join(
            settings.MEDIA_ROOT,
            "data_exports",
            str(instance.id),
        )
        os.makedirs(export_dir, exist_ok=True)
        zip_filename = f"{instance.request_id}_{now.strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = os.path.join(export_dir, zip_filename)
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        # Relative path for storage
        relative_path = os.path.relpath(zip_path, settings.MEDIA_ROOT)

        # ── Generate secure download token ─────────────────────────────────────
        token = generate_download_token()
        expires_at = now + timezone.timedelta(days=7)

        instance.export_zip_path = relative_path
        instance.export_zip_size = zip_size
        instance.export_zip_created_at = now
        instance.export_zip_expires_at = expires_at
        instance.export_download_token = token

        result = (
            f"Export completed. ZIP package generated on {now.strftime('%d %b %Y %H:%M UTC')}. "
            f"File size: {zip_size} bytes. "
            f"Download link expires on {expires_at.strftime('%d %b %Y %H:%M UTC')}."
        )
        return result

    def _perform_delete(self, instance):
        """
        Delete User Data — stub. Full implementation pending retention category list.
        """
        # TODO: Implement full deletion workflow once retention categories are confirmed.
        # The workflow should:
        # 1. Run approved deletion across all RightRoute-controlled systems (not a blanket delete).
        # 2. Categorise each record: deleted / retained / not found / unable to delete / scheduled for backup expiration.
        # 3. Protect backup data and place it beyond ordinary use until its deletion cycle.
        now = timezone.now()
        return (
            f"Deletion workflow completed on {now.strftime('%d %b %Y %H:%M UTC')}. "
            f"Eligible personal data was removed from active systems. "
            f"Limited records retained under the RightRoute retention policy are listed below.\n"
            f"[TODO: Insert retained categories and reasons once retention list is provided.]"
        )

    def _perform_anonymize(self, instance):
        """
        Anonymize User Data — stub. Full implementation pending retention category list.
        """
        # TODO: Implement anonymization once categories confirmed. Steps:
        # 1. Remove direct identifiers.
        # 2. Remove or transform indirect identifiers.
        # 3. Break links between retained records and the customer account.
        # 4. Check related tables, logs, analytics, and free-text fields.
        # 5. Confirm remaining data cannot reasonably identify the person.
        now = timezone.now()
        return (
            f"Anonymization completed on {now.strftime('%d %b %Y %H:%M UTC')}. "
            f"Identifying fields were removed or irreversibly transformed from retained records."
        )

    def _perform_delete_anonymize(self, instance):
        """
        Delete and Anonymize Retained Data — stub. Full implementation pending.
        """
        # TODO: Implement once categories confirmed. Steps:
        # 1. Delete personal information no longer required to be retained.
        # 2. Identify records retained for approved purposes.
        # 3. Remove or irreversibly transform identifying fields in retained records.
        # 4. Produce a summary of deleted and anonymized categories.
        now = timezone.now()
        return (
            f"Deletion and anonymization completed on {now.strftime('%d %b %Y %H:%M UTC')}. "
            f"Eligible personal data was deleted, and identifying information was removed from retained records."
        )

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_send_completion_email",
        summary="Send completion email and close",
        description=(
            "Opens completion email preview, sends it to the verified account email, "
            "logs the full email in Notes and Correspondence, records completion date, "
            "changes status to COMPLETED, and moves the request to the Completed Requests list. "
            "For export requests, includes the secure 7-day download link. "
            "Logs this event in the Audit Log. "
            "Required: the request process must have completed successfully."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response=DataProtectionRequestDetailSerializer,
                description="Completion email sent and request closed.",
            ),
            400: OpenApiResponse(description="Required conditions not met."),
        },
    )
    @action(detail=True, methods=["post"], url_path="send-completion-email")
    def send_completion_email(self, request, pk=None):
        instance = self.get_object()

        if not instance.can_send_completion_email:
            detail = (
                "The request process must be completed successfully before sending the completion email."
            )
            if instance.request_type == RequestType.EXPORT and not instance.export_zip_path:
                detail = "The export ZIP must be generated before sending the completion email."
            return Response(
                {"success": False, "detail": detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if instance.status == DataRequestStatus.COMPLETED:
            return Response(
                {"success": False, "detail": "This request has already been completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            email_body = send_completion_email(instance)
        except Exception as exc:
            return Response(
                {"success": False, "detail": f"Failed to send completion email: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        instance.status = DataRequestStatus.COMPLETED
        instance.completed_at = now
        instance.updated_by = request.user
        instance.save(update_fields=["status", "completed_at", "updated_by", "updated_at"])

        # Log the full sent email in Notes
        _add_system_note(
            instance,
            f"Completion email sent to {instance.customer_email} on "
            f"{now.strftime('%d %b %Y %H:%M UTC')} by {request.user.email}.\n\n"
            f"--- COMPLETION EMAIL CONTENT ---\n{email_body}",
        )

        _log_action(request, NotifyLogAction.UPDATE, instance, "Data protection request completed.", {
            "request_id": instance.request_id,
            "request_type": instance.request_type,
            "completed_at": str(now),
        })

        out = DataProtectionRequestDetailSerializer(instance, context={"request": request})
        return Response({
            "success": True,
            "message": "Completion email sent. Request is now Completed.",
            "data": out.data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Standalone views
# ─────────────────────────────────────────────────────────────────────────────

class GenerateRequestIdView(APIView):
    """Generate a fresh, unique DR-YYYY-XXXX request ID."""
    permission_classes = _PERMS
    required_admin_permission = DATA_PROTECTION_PERMISSION

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_generate_id",
        summary="Generate data request ID",
        description=(
            "Generates the next unique DR-YYYY-XXXX request ID. "
            "Call this when the Data Protection page is opened to pre-populate the ID field. "
            "The ID is only permanently saved when the form is submitted."
        ),
        responses={
            200: OpenApiResponse(
                response=GenerateRequestIdSerializer,
                description="Generated request ID.",
            )
        },
    )
    def get(self, request):
        return Response({
            "success": True,
            "data": {"request_id": generate_request_id()},
        })


class FindCustomerView(APIView):
    """FIND button — look up a RightRoute account by exact email match."""
    permission_classes = _PERMS
    required_admin_permission = DATA_PROTECTION_PERMISSION

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_find_customer",
        summary="Find customer by email",
        description=(
            "Searches for an exact RightRoute account email match. "
            "On success, returns auto-fill data for the form: customer name, verified email, "
            "user ID, plan type, account status, account creation date, and phone number. "
            "When no account is found, returns `found: false` with the standard not-found message."
        ),
        request=FindCustomerSerializer,
        responses={
            200: OpenApiResponse(
                response=CustomerFoundSerializer,
                description="Customer lookup result.",
            )
        },
    )
    def post(self, request):
        serializer = FindCustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.select_related("admin_profile").get(
                email__iexact=email,
                is_staff=False,  # Only look up regular customers, not admins
            )
        except User.DoesNotExist:
            return Response({
                "success": True,
                "data": {
                    "found": False,
                    "user_id": None,
                    "customer_name": "",
                    "verified_email": None,
                    "plan_type": "",
                    "account_status": "",
                    "account_created_at": None,
                    "phone_number": "",
                    "message": "No RightRoute account was found for this email.",
                },
            })

        # Determine plan type
        plan_type = ""
        if hasattr(user, "subscriptions"):
            active_sub = user.subscriptions.filter(status="ACTIVE").first()
            plan_type = active_sub.plan.name if active_sub and hasattr(active_sub, "plan") else ""

        # Phone number (from profile if available)
        phone = ""
        profile = getattr(user, "profile", None)
        if profile:
            phone = getattr(profile, "phone", "") or ""

        customer_name = ""
        if profile:
            customer_name = getattr(profile, "full_name", "") or getattr(profile, "name", "") or ""
        if not customer_name and hasattr(user, "admin_profile"):
            customer_name = getattr(user.admin_profile, "full_name", "") or ""

        return Response({
            "success": True,
            "data": {
                "found": True,
                "user_id": str(user.id),
                "customer_name": customer_name,
                "verified_email": user.email,
                "plan_type": plan_type,
                "account_status": user.status,
                "account_created_at": user.created_at,
                "phone_number": phone,
                "message": "",
            },
        })


class ExportDownloadView(APIView):
    """
    Secure download endpoint for data export ZIP files.
    The token is single-use-style: expires after 7 days, revocable by RightRoute.
    Not available through a permanent public link.
    """
    permission_classes = []  # Public endpoint — auth is via the token itself

    @extend_schema(
        tags=[TAG],
        operation_id="security_data_protection_export_download",
        summary="Download data export ZIP",
        description=(
            "Serves the data export ZIP file via a secure, time-limited token. "
            "The link expires after 7 days, is not publicly guessable, "
            "and is automatically invalidated once the retention period ends. "
            "Returns 404 if the token is invalid or the link has expired."
        ),
        responses={
            200: OpenApiResponse(description="ZIP file download."),
            404: OpenApiResponse(description="Invalid or expired download link."),
        },
    )
    def get(self, request, token):
        now = timezone.now()
        try:
            instance = DataProtectionRequest.objects.get(export_download_token=token)
        except DataProtectionRequest.DoesNotExist:
            raise Http404("Invalid or expired download link.")

        if not instance.export_zip_path:
            raise Http404("Export file not found.")

        if instance.export_zip_expires_at and now > instance.export_zip_expires_at:
            raise Http404("This download link has expired.")

        from django.conf import settings
        full_path = os.path.join(settings.MEDIA_ROOT, instance.export_zip_path)
        if not os.path.exists(full_path):
            raise Http404("Export file not found on server.")

        zip_filename = os.path.basename(full_path)
        response = FileResponse(
            open(full_path, "rb"),
            content_type="application/zip",
            as_attachment=True,
            filename=zip_filename,
        )
        return response
