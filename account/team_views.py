from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.mixins import ListModelMixin
from rest_framework.exceptions import ValidationError
from core.constants import TeamMemberInviteStatus, TeamMemberStatus
from rest_framework.views import APIView
from .models import TeamMember, TeamMemberInvite
from django.utils import timezone
from .team_serializers import (
    TeamDetailSerializer,
    TeamMemberSerializer,
    TeamMemberCreateSerializer,
    TeamMemberBulkDeleteSerializer,
    TeamMemberUpdateSerializer
)
from django.conf import settings
from django.db import transaction
from django.db.models import Q


class TeamViewSet(ListModelMixin, GenericViewSet):
    permission_classes = [IsAuthenticated]

    def get_team(self):
        return self.request.user.owned_team
    
    def list(self, request, *args, **kwargs):
        serializer = TeamDetailSerializer(
            self.get_team()
        )
        return Response(
            {
                "success": True,
                "data": serializer.data
            }
        )

    @action(detail=False, methods=["get"], url_path="members")
    def members(self, request):
        queryset = (
            TeamMember.objects
            .select_related("user")
            .filter(team=self.get_team())
            .order_by("-joined_at")
        )
        
        status_param = request.query_params.get("status")
        if status_param is not None:
            status_bool = status_param.lower() == "true"
            queryset = queryset.filter(status=status_bool)
        
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(user__email__icontains=search)
            )
        
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": TeamMemberSerializer(queryset, many=True).data
            }
        )

    def send_invite(self, team, member):
        invite = TeamMemberInvite.objects.create(
            team=team,
            team_member_object=member,
            invited_to=member.user,
            expires_at=timezone.now() + timezone.timedelta(days=1)
        )
        accept_link = f"{settings.FRONTEND_URL}/team/invite/{invite.uuid}/accept"
        return invite.uuid, accept_link
    
    @members.mapping.post
    def add_member(self, request):
        try:
            with transaction.atomic():
                serializer = TeamMemberCreateSerializer(data=request.data, context={"request": request})
                serializer.is_valid(raise_exception=True)
                
                user = serializer.validated_data["user"]
                team = self.get_team()
                member, created = TeamMember.objects.get_or_create(team=team,user=user, defaults={
                    "status": False
                })
                
                invite_uuid, accept_link = self.send_invite(team, member)
                return Response({
                    "success": True,
                    "message": "Invitation sent successfully.",
                    "data": {
                        "invite_id": str(invite_uuid),
                        "accept_link": accept_link
                    }
                }, status=status.HTTP_201_CREATED)
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=["get"], url_path=r"member/(?P<member_id>[^/.]+)")
    def detail_member(self, request, member_id=None):
        member = get_object_or_404(TeamMember, id=member_id, team=self.get_team())
        return Response(
            {
                "success": True,
                "data": TeamMemberSerializer(member).data
            }
        )
    
    @detail_member.mapping.patch
    def update_member(self, request, member_id=None):
        member = get_object_or_404(TeamMember, id=member_id, team=self.get_team())
        serializer = TeamMemberUpdateSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Member updated successfully.",
                "data": TeamMemberSerializer(member).data
            }
        )
    
    @action(detail=False, methods=["post"], url_path="remove-member")
    def remove_member(self, request, *args, **kwargs):
        serializer = TeamMemberBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member_ids = serializer.validated_data["team_member_ids"]
        team = self.get_team()
        members = TeamMember.objects.filter(
            id__in=member_ids,
            team=team
        )
        
        deleted_count = members.count()
        members.delete()
        return Response(
            {
                "success": True,
                "message": f"{deleted_count} member(s) removed successfully."
            },
            status=status.HTTP_200_OK
        )

class AcceptTeamInviteView(APIView):
    def get(self, request, uuid):
        try:
            invite = TeamMemberInvite.objects.select_related(
                "team_member_object",
                "team_member_object__user",
                "team"
            ).get(uuid=uuid)
        except TeamMemberInvite.DoesNotExist:
            return Response({
                "success": False,
                "message": "Invalid invite link."
            }, status=status.HTTP_404_NOT_FOUND)
        
        if invite.status != TeamMemberInviteStatus.PENDING:
            return Response({
                "success": False,
                "message": f"Invite already {invite.status.capitalize()}."
            }, status=status.HTTP_400_BAD_REQUEST)
        if invite.expires_at < timezone.now():
            return Response({
                "success": False,
                "message": "Invite expired."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        member = invite.team_member_object
        member.status = TeamMemberStatus.ACTIVE
        member.save()

        invite.status = TeamMemberInviteStatus.ACCEPT
        invite.save()

        return Response({
            "success": True,
            "message": "Team invite accepted successfully."
        })

