from rest_framework.permissions import BasePermission
from core.constants import UserType

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

class IsAdminUserPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.method in SAFE_METHODS or
            request.user and
            request.user.is_authenticated and
            request.user.user_type == UserType.ADMIN
        )

