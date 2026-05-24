from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve as static_serve
import os
from django.http import JsonResponse
from django.utils.timezone import now
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

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
    

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", Home, name="WelcomeAPI"),
    
    # app urls include
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

