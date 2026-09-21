from django.urls import path
from team_dashboard.views import (
    # Auth Views
    TeamLoginView,
    TeamVerifyOTPView,
    TeamResendOTPView,
    TeamSessionView,
    TeamLogoutView,
    # Manage — Email/Password
    TeamManageSendOTPView,
    TeamManageChangeEmailView,
    TeamManageChangePasswordView,
    # Manage — Admin Users
    TeamAdminUsersListView,
    TeamAdminUserDetailView,
    TeamAdminUserLockView,
    TeamAdminUserUnlockView,
    TeamAdminUserBulkActionView,
    TeamAdminGeneratePasswordView,
    # Manage — Team Users
    TeamUsersListView,
    TeamUsersImportCSVView,
    TeamUsersDownloadCSVView,
    TeamUsersBulkRemoveView,
    TeamUserDetailView,
    # Manage — Route History
    TeamRouteHistoryListView,
    TeamRouteWaypointsView,
    TeamRouteHistoryBulkDeleteView,
    TeamRouteHistoryDownloadCSVView,
    # Manage — Plan
    TeamPlanView,
    # Utility
    TeamPermissionTreeView,
)
from supports.views import (
    TeamContactInfoView,
    TeamTopicsDictionaryView,
    TeamTicketPrefillView,
    TeamSubmitTicketView,
    TeamMyTicketsListView,
    TeamSupportResourcesListView,
    TeamSupportResourceDownloadView,
)

urlpatterns = [
    # -------------------------------------------------------------
    # AUTHENTICATION
    # -------------------------------------------------------------
    path("auth/login/", TeamLoginView.as_view(), name="team-login"),
    path("auth/verify-otp/", TeamVerifyOTPView.as_view(), name="team-verify-otp"),
    path("auth/resend-otp/", TeamResendOTPView.as_view(), name="team-resend-otp"),
    path("auth/session/", TeamSessionView.as_view(), name="team-session"),
    path("auth/logout/", TeamLogoutView.as_view(), name="team-logout"),

    # -------------------------------------------------------------
    # 1. MANAGE — EMAIL / PASSWORD
    # -------------------------------------------------------------
    path("manage/email-password/send-code/", TeamManageSendOTPView.as_view(), name="team-manage-send-otp"),
    path("manage/email-password/change-email/", TeamManageChangeEmailView.as_view(), name="team-manage-change-email"),
    path("manage/email-password/change-password/", TeamManageChangePasswordView.as_view(), name="team-manage-change-password"),

    # -------------------------------------------------------------
    # 2. MANAGE — ADMIN USERS (Super Admin)
    # -------------------------------------------------------------
    path("manage/admin-users/", TeamAdminUsersListView.as_view(), name="team-admin-users-list"),
    path("manage/admin-users/generate-password/", TeamAdminGeneratePasswordView.as_view(), name="team-admin-generate-password"),
    path("manage/admin-users/bulk-action/", TeamAdminUserBulkActionView.as_view(), name="team-admin-bulk-action"),
    path("manage/admin-users/<int:user_id>/", TeamAdminUserDetailView.as_view(), name="team-admin-user-detail"),
    path("manage/admin-users/<int:user_id>/lock/", TeamAdminUserLockView.as_view(), name="team-admin-user-lock"),
    path("manage/admin-users/<int:user_id>/unlock/", TeamAdminUserUnlockView.as_view(), name="team-admin-user-unlock"),

    # -------------------------------------------------------------
    # 3. MANAGE — TEAM USERS (DRIVERS)
    # -------------------------------------------------------------
    path("manage/team-users/", TeamUsersListView.as_view(), name="team-users-list"),
    path("manage/team-users/import/", TeamUsersImportCSVView.as_view(), name="team-users-import-csv"),
    path("manage/team-users/download/", TeamUsersDownloadCSVView.as_view(), name="team-users-download-csv"),
    path("manage/team-users/remove/", TeamUsersBulkRemoveView.as_view(), name="team-users-bulk-remove"),
    path("manage/team-users/<int:member_id>/", TeamUserDetailView.as_view(), name="team-user-detail"),

    # -------------------------------------------------------------
    # 4. MANAGE — ROUTE HISTORY
    # -------------------------------------------------------------
    path("manage/route-history/", TeamRouteHistoryListView.as_view(), name="team-route-history-list"),
    path("manage/route-history/<int:route_id>/waypoints/", TeamRouteWaypointsView.as_view(), name="team-route-waypoints"),
    path("manage/route-history/bulk-delete/", TeamRouteHistoryBulkDeleteView.as_view(), name="team-route-history-bulk-delete"),
    path("manage/route-history/download/", TeamRouteHistoryDownloadCSVView.as_view(), name="team-route-history-download-csv"),

    # -------------------------------------------------------------
    # 5. MANAGE — PLAN
    # -------------------------------------------------------------
    path("manage/plan/", TeamPlanView.as_view(), name="team-plan"),

    # -------------------------------------------------------------
    # 6. PERMISSIONS REFERENCE
    # -------------------------------------------------------------
    path("manage/permissions-tree/", TeamPermissionTreeView.as_view(), name="team-permissions-tree"),

    # -------------------------------------------------------------
    # 7. SUPPORT SECTION
    # -------------------------------------------------------------
    path("support/contact-info/", TeamContactInfoView.as_view(), name="team-dashboard-support-contact-info"),
    path("support/topics/", TeamTopicsDictionaryView.as_view(), name="team-dashboard-support-topics"),
    path("support/prefill/", TeamTicketPrefillView.as_view(), name="team-dashboard-support-prefill"),
    path("support/submit-ticket/", TeamSubmitTicketView.as_view(), name="team-dashboard-support-submit-ticket"),
    path("support/my-tickets/", TeamMyTicketsListView.as_view(), name="team-dashboard-support-my-tickets"),
    path("support/resources/", TeamSupportResourcesListView.as_view(), name="team-dashboard-support-resources"),
    path("support/resources/<int:resource_id>/download/", TeamSupportResourceDownloadView.as_view(), name="team-dashboard-support-resource-download"),
]


