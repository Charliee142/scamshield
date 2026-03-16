# core/urls.py
from django.urls import path

from core.whatsapp_bot import whatsapp_webhook
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('webhook/', whatsapp_webhook, name='whatsapp_webhook'),
    path('education/', views.education_coach, name='education_coach'),
]