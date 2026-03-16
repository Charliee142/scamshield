# core/models.py

from django.db import models
from django.utils import timezone

NIGERIAN_STATES = [
    ('lagos', 'Lagos'), ('abuja', 'Abuja'), ('kano', 'Kano'),
    ('rivers', 'Rivers'), ('oyo', 'Oyo'), ('delta', 'Delta'),
    ('anambra', 'Anambra'), ('enugu', 'Enugu'), ('kaduna', 'Kaduna'),
    ('ogun', 'Ogun'), ('imo', 'Imo'), ('borno', 'Borno'),
    ('katsina', 'Katsina'), ('edo', 'Edo'), ('cross_river', 'Cross River'),
    ('akwa_ibom', 'Akwa Ibom'), ('sokoto', 'Sokoto'), ('osun', 'Osun'),
    ('ondo', 'Ondo'), ('benue', 'Benue'), ('adamawa', 'Adamawa'),
    ('ekiti', 'Ekiti'), ('kwara', 'Kwara'), ('niger', 'Niger'),
    ('plateau', 'Plateau'), ('taraba', 'Taraba'), ('nasarawa', 'Nasarawa'),
    ('gombe', 'Gombe'), ('zamfara', 'Zamfara'), ('kebbi', 'Kebbi'),
    ('jigawa', 'Jigawa'), ('yobe', 'Yobe'), ('bauchi', 'Bauchi'),
    ('bayelsa', 'Bayelsa'), ('ebonyi', 'Ebonyi'), ('abia', 'Abia'),
    ('other', 'Other'),
]

SCAM_TYPES = [
    ('investment', 'Investment Fraud'),
    ('bank_impersonation', 'Bank Impersonation'),
    ('job_scam', 'Fake Job Offer'),
    ('lottery', 'Lottery Scam'),
    ('romance', 'Romance Scam'),
    ('phishing', 'Phishing'),
    ('fake_alert', 'Fake Bank Alert'),
    ('crypto', 'Crypto Scam'),
    ('other', 'Other'),
]

class ScamScan(models.Model):
    """Records every message scan performed"""
    message_text = models.TextField()
    risk_level = models.CharField(max_length=20)   # HIGH, MEDIUM, LOW
    confidence = models.IntegerField(default=0)     # 0-100
    reasons = models.JSONField(default=list)
    ai_explanation = models.TextField(blank=True)
    scam_type = models.CharField(max_length=50, blank=True)
    state = models.CharField(max_length=50, choices=NIGERIAN_STATES, default='other')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.risk_level} | {self.created_at.strftime('%d %b %Y')}"


class BankAlertScan(models.Model):
    """Records bank alert image scans"""
    image = models.ImageField(upload_to='bank_alerts/')
    extracted_text = models.TextField(blank=True)
    risk_level = models.CharField(max_length=20)
    confidence = models.IntegerField(default=0)
    reasons = models.JSONField(default=list)
    state = models.CharField(max_length=50, choices=NIGERIAN_STATES, default='other')
    created_at = models.DateTimeField(auto_now_add=True)


class ScamReport(models.Model):
    """Community submitted scam reports"""
    phone_number = models.CharField(max_length=15, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    scam_type = models.CharField(max_length=50, choices=SCAM_TYPES)
    description = models.TextField()
    screenshot = models.ImageField(upload_to='scam_screenshots/', blank=True, null=True)
    state = models.CharField(max_length=50, choices=NIGERIAN_STATES)
    verified = models.BooleanField(default=False)
    report_count = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.scam_type} | {self.phone_number or self.account_number}"


class ScamPattern(models.Model):
    """AI-learned scam patterns from reports"""
    pattern_name = models.CharField(max_length=200)
    keywords = models.JSONField(default=list)
    scam_type = models.CharField(max_length=50)
    occurrence_count = models.IntegerField(default=1)
    confidence_score = models.FloatField(default=0.5)
    is_active = models.BooleanField(default=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.pattern_name} ({self.occurrence_count} reports)"


class LinkScan(models.Model):
    """Records every URL scan performed"""
    url = models.URLField(max_length=2000)
    clean_url = models.CharField(max_length=2000, blank=True)  # normalized
    risk_level = models.CharField(max_length=20)   # HIGH, MEDIUM, LOW, SAFE
    confidence = models.IntegerField(default=0)
    reasons = models.JSONField(default=list)
    threat_type = models.CharField(max_length=100, blank=True)  # MALWARE, PHISHING, etc.
    ai_explanation = models.TextField(blank=True)
    is_shortener = models.BooleanField(default=False)
    final_url = models.URLField(max_length=2000, blank=True)  # after redirect
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    state = models.CharField(max_length=50, choices=NIGERIAN_STATES, default='other')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.risk_level} | {self.url[:60]}"



class AlertSubscriber(models.Model):
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True)
    state = models.CharField(max_length=50)
    scam_types = models.JSONField(default=list)  # which types to alert on
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.email or self.phone} | {self.state}"
    

# Trigger alert when new HIGH scam is detected in their state
def notify_subscribers(state: str, scam_type: str, analysis: dict):
    from django.core.mail import send_mail
    subscribers = AlertSubscriber.objects.filter(
        state=state, is_active=True
    )
    for sub in subscribers:
        send_mail(
            subject=f'⚠️ ScamShield Alert: New {scam_type} scam in {state}',
            message=f'A new scam has been detected in your area.\n\n{analysis["explanation"]}',
            from_email='alerts@scamshield.ng',
            recipient_list=[sub.email],
        )