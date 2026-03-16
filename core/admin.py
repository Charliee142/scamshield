from django.contrib import admin

from .models import *

@admin.register(ScamScan)
class ScamScanAdmin(admin.ModelAdmin):
    list_display = ('id', 'risk_level', 'confidence', 'scam_type', 'state', 'created_at')
    list_filter = ('risk_level', 'scam_type', 'state', 'created_at')
    search_fields = ('message_text', 'reasons__icontains')


@admin.register(BankAlertScan)
class BankAlertScanAdmin(admin.ModelAdmin):
    list_display = ('id', 'risk_level', 'confidence', 'state', 'created_at')
    list_filter = ('risk_level', 'state', 'created_at')
    search_fields = ('extracted_text', 'reasons__icontains')


@admin.register(ScamReport)
class ScamReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'scam_type', 'phone_number', 'account_number', 'bank_name', 'state', 'verified', 'report_count', 'created_at')
    list_filter = ('scam_type', 'state', 'verified', 'created_at')
    search_fields = ('description', 'phone_number', 'account_number')


@admin.register(ScamPattern)
class ScamPatternAdmin(admin.ModelAdmin):
    list_display = ('id', 'pattern_name', 'scam_type', 'occurrence_count', 'confidence_score', 'is_active', 'first_seen')
    list_filter = ('scam_type', 'is_active', 'first_seen')
    search_fields = ('pattern_name', 'keywords__icontains')


@admin.register(LinkScan)
class LinkScanAdmin(admin.ModelAdmin):
    list_display = ('id', 'url', 'threat_type', 'risk_level', 'created_at')
    list_filter = ('threat_type', 'risk_level', 'created_at')
    search_fields = ('url', 'description__icontains')