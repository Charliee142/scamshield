from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.whatsapp_bot import whatsapp_webhook

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('scanner/', include('scanner.urls')),
    path('community/', include('community.urls')),
    path('chat/', include('chatbot.urls')),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)