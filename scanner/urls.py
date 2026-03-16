# scanner/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('whatsapp/', views.whatsapp_scanner, name='whatsapp_scanner'),
    path('bank-alert/', views.bank_alert_detector, name='bank_alert'),
    path('map/', views.scam_map, name='scam_map'),#
    path('api/map-data/', views.map_data_api, name='map_data_api'),
    path('link/', views.link_scanner, name='link_scanner'),
]