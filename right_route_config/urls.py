from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve as static_serve
import os
from django.http import JsonResponse
from django.utils.timezone import now
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from subscription.views import SubscriptionPlanPayActionView
from account.team_views import AcceptTeamInviteView

# Administrator Dashboard Customized---
admin.site.site_title = "HomeWorkerFinder"
admin.site.site_header = "HomeWorkerFinder"
admin.site.app_index = "Welcome to Home Worker Finder"

# Main Base API Online Template
def Home(request):
    return JsonResponse({
        "application": "RightRoutes API",
        "status": "online 🚀",
        "server_time": now(),
        "message": "Backend server is running successfully."
    })

def api_endpoint(request):
    return JsonResponse(
        {
            "application": "API V1 Endpoint!",
            "status": "online 🚀",
            "server_time": now(),
        }
    )

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", Home, name="WelcomeAPI"),
    
    # Payment Action API
    path("purchase/pay/for/subscription/", SubscriptionPlanPayActionView.as_view(), name="payment-action-api"),
    path("team/invite/<uuid:uuid>/accept/", AcceptTeamInviteView.as_view(), name="invite-link"),
    
    # app urls include
    path("api/v1/", api_endpoint, name="api_endpoint"),
    path("api/v1/", include("account.urls")),
    path("api/v1/", include("core.urls")),
    path("api/v1/", include("notification.urls")),
    path("api/v1/", include("route.urls")),
    path("api/v1/", include("subscription.urls")),
    
    # API schema
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Swagger UI
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Redoc UI
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]


SERVE_MEDIA = os.getenv("SERVE_MEDIA", "False").strip().lower() in ("true","1","yes")

if SERVE_MEDIA:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', static_serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^static/(?P<path>.*)$', static_serve, {'document_root': settings.STATIC_ROOT}),
    ]

