from django.urls import path, re_path, include
from rest_framework.routers import DefaultRouter
from .admin_views import (
    AdminLoginView
)
from .views import (
    DeviceInfoView,
    ContinueAPIView,
    LoginAPIView,
    CreatePasswordAPIView,
    VerifyOTPAPIView,
    RefreshTokenAPIView,
    LogoutAPIView,
    VerifyTokenAPIView, ChangePasswordView, ResendOTPAPIView, ChangeEmailAPIView, AccountDeleteAPIView,
    
    ForgetPasswordView, ResetPasswordView,
    
    CurrentUserAPIView, AcceptTeamMemberInvitation
)
from .team_views import TeamViewSet

router = DefaultRouter()
router.register(r"team", TeamViewSet, basename="team")


urlpatterns = [
    path("auth/device-info/",DeviceInfoView.as_view(),name="device-info"),
    path("auth/continue/",ContinueAPIView.as_view(),name="continue"),
    path("auth/continue/",ContinueAPIView.as_view(),name="continue"),
    path("auth/login/",LoginAPIView.as_view(),name="login"),
    path("auth/create-password/",CreatePasswordAPIView.as_view(),name="create-password"),
    path("auth/verify-otp/",VerifyOTPAPIView.as_view(),name="verify-otp"),
    
    path("auth/forget-password/",ForgetPasswordView.as_view(),name="forget-password"),
    path("auth/reset-password/",ResetPasswordView.as_view(),name="reset-password"),
    
    path("auth/refresh-token/",RefreshTokenAPIView.as_view(),name="refresh-token"),
    path("auth/verify-token/",VerifyTokenAPIView.as_view(),name="verify-token"),
    path("auth/logout/",LogoutAPIView.as_view(),name="logout"),
    path("auth/change-password/",ChangePasswordView.as_view(),name="change-password"),
    
    path("auth/resend-otp/", ResendOTPAPIView.as_view(), name="resend-otp",),
    path("auth/change-email/", ChangeEmailAPIView.as_view(), name="change-email",),
    path("auth/account-delete/", AccountDeleteAPIView.as_view(), name="account-delete",),
    
    path("userinfo/", CurrentUserAPIView.as_view(), name="current-user"),
    path("team-member-invitation/", AcceptTeamMemberInvitation.as_view(), name="invitation-action"),
    
    path("auth/admin/login/",AdminLoginView.as_view(),name="admin-login"),
    
    # TeamViewSet
    path("", include(router.urls))
]

