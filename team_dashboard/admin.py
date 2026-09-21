from django.contrib import admin
from team_dashboard.models import TeamAdminProfile


@admin.register(TeamAdminProfile)
class TeamAdminProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "role", "full_name", "phone", "is_active", "created_at")
    list_filter = ("role", "is_active", "team")
    search_fields = ("user__email", "full_name", "team__name", "phone")
    readonly_fields = ("created_at", "updated_at")
