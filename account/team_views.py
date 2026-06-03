from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.mixins import ListModelMixin
from rest_framework.exceptions import ValidationError

from .models import TeamMember
from .team_serializers import (
    TeamDetailSerializer,
    TeamMemberSerializer,
    TeamMemberCreateSerializer,
)


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
            .filter(
                team=self.get_team()
            )
            .order_by("-joined_at")
        )

        serializer = TeamMemberSerializer(queryset, many=True)

        return Response(
            {
                "success": True,
                "count": len(serializer.data),
                "data": serializer.data
            }
        )

    @members.mapping.post
    def add_member(self, request):
        try:
            serializer = TeamMemberCreateSerializer(data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            TeamMember.objects.create(team=self.get_team(),user=serializer.validated_data["user"])
            return Response(
                {
                    "success": True,
                    "detail": "Member added successfully."
                },
                status=status.HTTP_201_CREATED
            )
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    # @action(detail=True, methods=["delete"], url_path="remove-member")
    # def remove_member(self, request, pk=None):
    #     member = TeamMember.objects.filter(
    #         uuid=pk,
    #         team=self.get_team()
    #     ).first()

    #     if not member:
    #         return Response(
    #             {
    #                 "success": False,
    #                 "detail": "Member not found."
    #             },
    #             status=status.HTTP_404_NOT_FOUND
    #         )

    #     member.delete()

    #     return Response(
    #         {
    #             "success": True,
    #             "detail": "Member removed successfully."
    #         }
    #     )



