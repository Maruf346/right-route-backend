from django.urls import path
from team_dashboard.views import (
    TeamLoginView,
    TeamVerifyOTPView,
    TeamResendOTPView,
    TeamSessionView,
    TeamLogoutView,
)

urlpatterns = [
    path("auth/login/", TeamLoginView.as_view(), name="team-login"),
    path("auth/verify-otp/", TeamVerifyOTPView.as_view(), name="team-verify-otp"),
    path("auth/resend-otp/", TeamResendOTPView.as_view(), name="team-resend-otp"),
    path("auth/session/", TeamSessionView.as_view(), name="team-session"),
    path("auth/logout/", TeamLogoutView.as_view(), name="team-logout"),
]
