# community/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('report/', views.report_scam, name='report_scam'),
    path('lookup/', views.phone_lookup, name='phone_lookup'),
]