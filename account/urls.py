from django.urls import path

from .views import (
    ContinueAPIView,
    LoginAPIView,
    CreatePasswordAPIView,
    VerifyOTPAPIView,
    RefreshTokenAPIView,
    LogoutAPIView,
    VerifyTokenAPIView
)

urlpatterns = [
    path("auth/continue/",ContinueAPIView.as_view(),name="continue"),
    path("auth/login/",LoginAPIView.as_view(),name="login"),
    path("auth/create-password/",CreatePasswordAPIView.as_view(),name="create-password"),
    path("auth/verify-otp/",VerifyOTPAPIView.as_view(),name="verify-otp"),
    path("auth/refresh-token/",RefreshTokenAPIView.as_view(),name="refresh-token"),
    path("auth/verify-token/",VerifyTokenAPIView.as_view(),name="verify-token"),
    path("auth/logout/",LogoutAPIView.as_view(),name="logout"),
]