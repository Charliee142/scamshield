from django.urls import path
from . import views
#
urlpatterns = [
    path('', views.chatbot_page, name='chatbot'),
    path('api/chat/', views.chat_api,     name='chat_api'),
    path('api/new/', views.new_session,  name='new_session'),
    path('api/history/<uuid:session_id>/', views.get_history, name='chat_history'),
 ]