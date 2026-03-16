from django.db import models
import uuid
 
 
class ChatSession(models.Model):
    """One browser session = one chat thread"""
    session_id  = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title       = models.CharField(max_length=200, default='New Chat')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    message_count = models.IntegerField(default=0)
 
    class Meta:
        ordering = ['-updated_at']
 
    def __str__(self):
        return f"Session {self.session_id} — {self.title}"
 
 
class ChatMessage(models.Model):
    ROLE_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]
 
    session   = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role      = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content   = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ['timestamp']
 
    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"