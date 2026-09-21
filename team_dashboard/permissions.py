from rest_framework.permissions import BasePermission
from team_dashboard.constants import TeamDashboardRole, TEAM_DASHBOARD_PERMISSIONS


def is_team_dashboard_user(user):
    """
    Returns True if user is an active team owner or team admin.
    """
    if not (user and user.is_authenticated and user.is_active):
        return False

    # Check if user has active TeamAdminProfile (sub-admin / assigned admin)
    profile = getattr(user, "team_admin_profile", None)
    if profile and profile.is_active and profile.team.is_active:
        return True

    # Check if user owns a team
    if hasattr(user, "owned_team") and user.owned_team.is_active:
        return True

    return False


def get_team_for_user(user):
    """
    Returns the active Team object for a user (as team admin or owner).
    """
    # Prioritize explicit team admin profile if assigned
    profile = getattr(user, "team_admin_profile", None)
    if profile and profile.is_active and profile.team.is_active:
        return profile.team

    if hasattr(user, "owned_team") and user.owned_team.is_active:
        return user.owned_team

    return None


def get_user_team_permissions(user):
    """
    Returns list of granted permissions for the Team Dashboard.
    Team owners and Super Admins receive all permissions.
    """
    if not is_team_dashboard_user(user):
        return []

    team = get_team_for_user(user)
    if not team:
        return []

    # If owner of the team, grant all permissions
    if team.owner_id == user.id:
        return TEAM_DASHBOARD_PERMISSIONS

    profile = getattr(user, "team_admin_profile", None)
    if profile:
        return profile.get_effective_permissions()

    return []


def is_team_super_admin(user):
    """
    Returns True if user is the Team Owner or has role == SUPER_ADMIN.
    """
    if not is_team_dashboard_user(user):
        return False
    team = get_team_for_user(user)
    if not team:
        return False
    if team.owner_id == user.id:
        return True
    profile = getattr(user, "team_admin_profile", None)
    if profile and profile.role == TeamDashboardRole.SUPER_ADMIN:
        return True
    return False


class IsTeamDashboardUser(BasePermission):
    message = "Team Dashboard access required."

    def has_permission(self, request, view):
        return is_team_dashboard_user(request.user)


class IsTeamSuperAdmin(BasePermission):
    message = "Super Admin privileges required to access this section."

    def has_permission(self, request, view):
        return is_team_super_admin(request.user)


class HasTeamDashboardPermission(BasePermission):
    message = "You do not have permission to access this Team Dashboard section."

    def has_permission(self, request, view):
        if not is_team_dashboard_user(request.user):
            return False

        if is_team_super_admin(request.user):
            return True

        required_permission = getattr(view, "required_team_permission", None)
        if not required_permission:
            return True

        permissions = get_user_team_permissions(request.user)
        if isinstance(required_permission, (list, tuple, set)):
            # If any of the required permissions is present
            return any(p in permissions for p in required_permission)

        if required_permission in permissions:
            return True

        # Check section-level wildcard (e.g. 'manage' grants all 'manage.*')
        section_key = required_permission.split(".")[0].lower()
        if section_key in permissions:
            return True

        return False

