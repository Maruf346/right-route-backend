from django.db import models
from core.common_models import BaseModel
from account.models import User, Team
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS


class TeamAdminProfile(BaseModel):
    """
    Profile for administrators within a specific Team/Fleet account.
    Super Admins (Team Owners) have full access to all sections.
    Sub-admins have custom granted permissions defined in permissions_json.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="team_admin_profile",
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="team_admins",
    )
    role = models.CharField(
        max_length=30,
        choices=TeamDashboardRole.choices,
        default=TeamDashboardRole.ADMIN,
    )
    full_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    permissions_json = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_team_admins",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_team_admins",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Team Admin Profile"
        verbose_name_plural = "Team Admin Profiles"

    def __str__(self):
        return f"{self.full_name or self.user.email} ({self.role}) - {self.team.name}"

    def get_effective_permissions(self):
        """Super Admin gets all permissions; sub-admin gets permissions_json."""
        if self.role == TeamDashboardRole.SUPER_ADMIN or getattr(self.team, "owner_id", None) == self.user_id:
            return TEAM_DASHBOARD_PERMISSIONS
        return self.permissions_json or []
