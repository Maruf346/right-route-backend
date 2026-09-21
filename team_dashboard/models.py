import random
import string
from django.db import models
from core.common_models import BaseModel
from account.models import User, Team
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS


def generate_unique_admin_user_id():
    """Generates a random display ID like USR-1082."""
    for _ in range(20):
        digits = "".join(random.choices(string.digits, k=4))
        user_id = f"USR-{digits}"
        if not TeamAdminProfile.objects.filter(user_id_display=user_id).exists():
            return user_id
    # Fallback to 6 digits if 4-digit space has collisions
    digits = "".join(random.choices(string.digits, k=6))
    return f"USR-{digits}"


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
    role_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Custom role label displayed in UI (e.g. 'Legal Adviser', 'Super Admin')",
    )
    user_id_display = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        help_text="Display User ID (e.g. 'USR-1082')",
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
        role_text = self.role_label or self.role
        return f"{self.full_name or self.user.email} ({role_text}) - {self.team.name}"

    def save(self, *args, **kwargs):
        if not self.user_id_display:
            self.user_id_display = generate_unique_admin_user_id()
        if not self.role_label:
            if self.role == TeamDashboardRole.SUPER_ADMIN or getattr(self.team, "owner_id", None) == self.user_id:
                self.role_label = "Super Admin"
            else:
                self.role_label = "Team Admin"
        super().save(*args, **kwargs)

    def get_effective_permissions(self):
        """Super Admin gets all permissions; sub-admin gets permissions_json."""
        if self.role == TeamDashboardRole.SUPER_ADMIN or getattr(self.team, "owner_id", None) == self.user_id:
            return TEAM_DASHBOARD_PERMISSIONS
        return self.permissions_json or []

