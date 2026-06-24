from rest_framework import serializers
from .models import Team, TeamMember
from account.models import User
from core.constants import TeamMemberStatus
from subscription.services.validators import TeamMemberValidator


class TeamMemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = TeamMember
        fields = "__all__"

class TeamDetailSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    used_members = serializers.SerializerMethodField()
    members = TeamMemberSerializer(many=True,read_only=True)

    class Meta:
        model = Team
        fields = "__all__"

    def get_used_members(self, obj):
        return obj.members.filter(
            status=True
        ).count()



class TeamMemberCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, attrs):
        request = self.context["request"]
        try:
            user = User.objects.get(
                email=attrs["email"]
            )
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "User not found."
            )
        TeamMemberValidator.validate_add_member(
            owner=request.user,
            target_user=user
        )
        attrs["user"] = user
        return attrs

class TeamMemberBulkDeleteSerializer(serializers.Serializer):
    team_member_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)

    def validate_team_member_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one ID is required.")
        return value

class TeamMemberUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = TeamMember
        fields = ["status"]
