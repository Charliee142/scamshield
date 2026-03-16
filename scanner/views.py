# scanner/views.py  — COMPLETE CLEAN FILE
# Fixes:
#   1. Removed duplicate imports and duplicate function definitions
#   2. bank_alert_detector now uses the correct field name 'image' (not 'alert_image')
#      and saves the file manually (not via default_storage) so full_path is reliable
#   3. Passes ocr_text → extracted_text to DB correctly

import os
import json
import logging

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.db.models import Count

from core.ai_engine import analyze_whatsapp_message, analyze_bank_alert, analyze_url
from core.models import ScamScan, BankAlertScan, ScamReport, LinkScan

logger = logging.getLogger(__name__)

# ── Allowed image types ──────────────────────────────────────────
ALLOWED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif']


def get_nigerian_states():
    return [
        ("abia", "Abia"),
        ("adamawa", "Adamawa"),
        ("akwa_ibom", "Akwa Ibom"),
        ("anambra", "Anambra"),
        ("bauchi", "Bauchi"),
        ("bayelsa", "Bayelsa"),
        ("benue", "Benue"),
        ("borno", "Borno"),
        ("cross_river", "Cross River"),
        ("delta", "Delta"),
        ("ebonyi", "Ebonyi"),
        ("edo", "Edo"),
        ("ekiti", "Ekiti"),
        ("enugu", "Enugu"),
        ("fct", "FCT - Abuja"),
        ("gombe", "Gombe"),
        ("imo", "Imo"),
        ("jigawa", "Jigawa"),
        ("kaduna", "Kaduna"),
        ("kano", "Kano"),
        ("katsina", "Katsina"),
        ("kebbi", "Kebbi"),
        ("kogi", "Kogi"),
        ("kwara", "Kwara"),
        ("lagos", "Lagos"),
        ("nasarawa", "Nasarawa"),
        ("niger", "Niger"),
        ("ogun", "Ogun"),
        ("ondo", "Ondo"),
        ("osun", "Osun"),
        ("oyo", "Oyo"),
        ("plateau", "Plateau"),
        ("rivers", "Rivers"),
        ("sokoto", "Sokoto"),
        ("taraba", "Taraba"),
        ("yobe", "Yobe"),
        ("zamfara", "Zamfara"),
    ]

# ── Nigerian states list ─────────────────────────────────────────
NIGERIAN_STATES = [
    ('abia', 'Abia'), ('adamawa', 'Adamawa'), ('akwa_ibom', 'Akwa Ibom'),
    ('anambra', 'Anambra'), ('bauchi', 'Bauchi'), ('bayelsa', 'Bayelsa'),
    ('benue', 'Benue'), ('borno', 'Borno'), ('cross_river', 'Cross River'),
    ('delta', 'Delta'), ('ebonyi', 'Ebonyi'), ('edo', 'Edo'),
    ('ekiti', 'Ekiti'), ('enugu', 'Enugu'), ('abuja', 'FCT (Abuja)'),
    ('gombe', 'Gombe'), ('imo', 'Imo'), ('jigawa', 'Jigawa'),
    ('kaduna', 'Kaduna'), ('kano', 'Kano'), ('katsina', 'Katsina'),
    ('kebbi', 'Kebbi'), ('kogi', 'Kogi'), ('kwara', 'Kwara'),
    ('lagos', 'Lagos'), ('nasarawa', 'Nasarawa'), ('niger', 'Niger'),
    ('ogun', 'Ogun'), ('ondo', 'Ondo'), ('osun', 'Osun'),
    ('oyo', 'Oyo'), ('plateau', 'Plateau'), ('rivers', 'Rivers'),
    ('sokoto', 'Sokoto'), ('taraba', 'Taraba'), ('yobe', 'Yobe'),
    ('zamfara', 'Zamfara'), ('other', 'Other / Not Listed'),
]

# ── Nigerian state coordinates (lat, lng) ────────────────────────
STATE_COORDS = {
    'lagos': (6.5244, 3.3792), 'abuja': (9.0579, 7.4951),
    'kano': (12.0022, 8.5919), 'rivers': (4.8156, 7.0498),
    'oyo': (7.3775, 3.9470),   'delta': (5.5251, 5.7358),
    'anambra': (6.2103, 7.0694), 'enugu': (6.4584, 7.5464),
    'kaduna': (10.5264, 7.4384), 'ogun': (6.9980, 3.4736),
    'imo': (5.4927, 7.0258),   'borno': (11.8333, 13.1500),
    'edo': (6.3350, 5.6037),   'cross_river': (5.8702, 8.5988),
    'akwa_ibom': (5.0073, 7.8494), 'katsina': (12.9891, 7.6006),
    'osun': (7.5629, 4.5200),  'ondo': (7.1000, 4.8400),
    'kwara': (8.4966, 4.5421), 'benue': (7.1905, 8.1306),
    'ekiti': (7.7190, 5.3110), 'niger': (9.9309, 5.5983),
    'plateau': (9.2182, 9.5179), 'taraba': (7.9995, 10.7744),
    'nasarawa': (8.5378, 8.3206), 'gombe': (10.2904, 11.1671),
    'sokoto': (13.0622, 5.2339), 'zamfara': (12.1700, 6.6600),
    'kebbi': (12.4539, 4.1975), 'jigawa': (12.2280, 9.5616),
    'yobe': (12.2939, 11.4390), 'bauchi': (10.3158, 9.8442),
    'bayelsa': (4.7719, 6.0699), 'ebonyi': (6.2649, 8.0137),
    'abia': (5.4527, 7.5248),  'adamawa': (9.3265, 12.3984),
    'kogi': (7.7337, 6.6906),
}


# ════════════════════════════════════════════════════════════════
#  HELPER
# ════════════════════════════════════════════════════════════════

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


# ════════════════════════════════════════════════════════════════
#  1. WHATSAPP SCANNER
# ════════════════════════════════════════════════════════════════

@require_http_methods(['GET', 'POST'])
def whatsapp_scanner(request):
    result       = None
    form_message = ''

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        state   = request.POST.get('state', 'other')

        if message:
            form_message = message
            analysis     = analyze_whatsapp_message(message)

            ScamScan.objects.create(
                message_text=message[:500],
                risk_level=analysis.get('risk_level', 'LOW'),
                confidence=int(analysis.get('confidence', 0)),
                reasons=analysis.get('reasons', []),
                ai_explanation=analysis.get('explanation', ''),
                scam_type=analysis.get('scam_type', 'other'),
                state=state,
                ip_address=get_client_ip(request),
            )
            result = analysis

    return render(request, 'scanner/whatsapp_scanner.html', {
        'result':          result,
        'form_message':    form_message,
        'nigerian_states': NIGERIAN_STATES,
    })


# ════════════════════════════════════════════════════════════════
#  2. BANK ALERT DETECTOR  ← THIS IS THE FIXED VERSION
#
#  Key changes vs your old code:
#  • Form field name is 'image'  (was 'alert_image' in old broken version)
#  • File is saved manually to media/bank_alerts/ so the path is 100% reliable
#  • Passes ocr_text (not extracted_text) to the DB — matches ai_engine output
#  • Full error handling so you always get a real error message, not 0% medium
# ════════════════════════════════════════════════════════════════

def bank_alert_detector(request):
    result   = None
    filename = ''

    if request.method == 'POST' and request.FILES.get('image'):
        uploaded = request.FILES['image']
        state    = request.POST.get('state', 'other')

        # ── Validate file type ───────────────────────────────────
        content_type = uploaded.content_type.lower()
        if content_type not in ALLOWED_TYPES:
            result = {
                'risk_level':  'MEDIUM',
                'confidence':  0,
                'reasons':     [f'File type "{content_type}" is not supported.'],
                'explanation': 'Please upload a JPEG, PNG, or WebP image.',
                'advice':      'Take a fresh screenshot and upload it.',
                'bank_name':   '',
                'amount':      '',
                'is_fake':     False,
            }
            return render(request, 'scanner/bank_alert_detector.html', {
                'result': result, 'filename': filename,
                'nigerian_states': NIGERIAN_STATES,
            })

        # ── Save file to media/bank_alerts/ ──────────────────────
        try:
            save_dir = os.path.join(settings.MEDIA_ROOT, 'bank_alerts')
            os.makedirs(save_dir, exist_ok=True)

            safe_name = uploaded.name.replace(' ', '_')
            save_path = os.path.join(save_dir, safe_name)
            filename  = safe_name

            with open(save_path, 'wb+') as dest:
                for chunk in uploaded.chunks():
                    dest.write(chunk)

        except Exception as e:
            logger.error(f"File save error: {e}")
            result = {
                'risk_level':  'MEDIUM',
                'confidence':  0,
                'reasons':     ['Failed to save the uploaded file.'],
                'explanation': str(e),
                'advice':      'Try uploading again.',
                'bank_name':   '', 'amount':  '', 'is_fake': False,
            }
            return render(request, 'scanner/bank_alert_detector.html', {
                'result': result, 'filename': filename,
                'nigerian_states': NIGERIAN_STATES,
            })

        # ── Run AI analysis ──────────────────────────────────────
        try:
            result = analyze_bank_alert(save_path)
        except Exception as e:
            logger.error(f"analyze_bank_alert error: {e}", exc_info=True)
            result = {
                'risk_level':  'MEDIUM',
                'confidence':  0,
                'reasons':     [f'Analysis error: {str(e)}'],
                'explanation': 'The AI could not analyze this image. Try a clearer screenshot.',
                'advice':      'Try uploading again.',
                'bank_name':   '', 'amount':  '', 'is_fake': False,
            }

        # ── Save scan to DB ──────────────────────────────────────
        try:
            BankAlertScan.objects.create(
                image=os.path.join('bank_alerts', safe_name),
                # 'ocr_text' is what ai_engine returns; map it to your model field
                extracted_text=result.get('ocr_text', '')[:2000],
                risk_level=result.get('risk_level', 'MEDIUM'),
                confidence=int(result.get('confidence', 0)),
                reasons=result.get('reasons', []),
                state=state,
            )
        except Exception as e:
            logger.warning(f"DB save skipped (non-fatal): {e}")

    return render(request, 'scanner/bank_alert_detector.html', {
        'result':          result,
        'filename':        filename,
        'nigerian_states': NIGERIAN_STATES,
    })


# ════════════════════════════════════════════════════════════════
#  3. SCAM MAP PAGE
# ════════════════════════════════════════════════════════════════

def scam_map(request):
    scan_counts   = ScamScan.objects.values('state').annotate(count=Count('id'))
    report_counts = ScamReport.objects.values('state').annotate(count=Count('id'))

    combined = {}
    for row in scan_counts:
        combined[row['state']] = combined.get(row['state'], 0) + row['count']
    for row in report_counts:
        combined[row['state']] = combined.get(row['state'], 0) + row['count']

    state_table = sorted(
        [
            {
                'state':      k.replace('_', ' ').title(),
                'state_slug': k,
                'count':      v,
                'risk':       'HIGH' if v >= 50 else ('MEDIUM' if v >= 20 else 'LOW'),
            }
            for k, v in combined.items()
            if k in STATE_COORDS
        ],
        key=lambda x: x['count'],
        reverse=True,
    )

    total_incidents = sum(combined.values())
    most_active     = state_table[0] if state_table else None

    return render(request, 'scanner/scam_map.html', {
        'state_table':     state_table,
        'total_incidents': total_incidents,
        'most_active':     most_active,
        'total_states':    len(state_table),
    })


# ════════════════════════════════════════════════════════════════
#  4. MAP DATA API (JSON for Leaflet)
# ════════════════════════════════════════════════════════════════

def map_data_api(request):
    scan_counts   = ScamScan.objects.values('state').annotate(count=Count('id'))
    report_counts = ScamReport.objects.values('state').annotate(count=Count('id'))

    combined = {}
    for row in scan_counts:
        combined[row['state']] = combined.get(row['state'], 0) + row['count']
    for row in report_counts:
        combined[row['state']] = combined.get(row['state'], 0) + row['count']

    # Demo seed so map is never blank on day 1
    if not combined:
        combined = {
            'lagos': 132, 'abuja': 42, 'rivers': 38,
            'kano': 21,   'oyo': 17,   'delta': 14,
            'anambra': 11, 'enugu': 9, 'kaduna': 7,
        }

    max_count = max(combined.values())
    total     = sum(combined.values())
    markers   = []

    for state_key, count in combined.items():
        if state_key not in STATE_COORDS:
            continue
        lat, lng  = STATE_COORDS[state_key]
        intensity = count / max_count
        color     = '#ff3d71' if intensity >= 0.6 else ('#ffd600' if intensity >= 0.3 else '#00c853')
        radius    = round(8 + (intensity * 32))

        markers.append({
            'state':  state_key.replace('_', ' ').title(),
            'lat':    lat,
            'lng':    lng,
            'count':  count,
            'color':  color,
            'radius': radius,
        })

    markers.sort(key=lambda m: m['count'], reverse=True)
    return JsonResponse({'markers': markers, 'total': total, 'max': max_count})


# ════════════════════════════════════════════════════════════════
#  5. LINK SCANNER
# ════════════════════════════════════════════════════════════════

def link_scanner(request):
    result = None
    url    = ''
    state  = 'other'

    if request.method == 'POST':
        url   = request.POST.get('url', '').strip()
        state = request.POST.get('state', 'other')

        if url:
            analysis = analyze_url(url)

            LinkScan.objects.create(
                url=url[:2000],
                risk_level=analysis.get('risk_level', 'LOW'),
                confidence=analysis.get('confidence', 0),
                reasons=analysis.get('reasons', []),
                threat_type=analysis.get('threat_type', ''),
                ai_explanation=analysis.get('explanation', ''),
                is_shortener=analysis.get('is_shortener', False),
                final_url=analysis.get('final_url', ''),
                state=state,
                ip_address=get_client_ip(request),
            )
            result = analysis

    return render(request, 'scanner/link_scanner.html', {
        'result':          result,
        'url':             url,
        'nigerian_states': NIGERIAN_STATES,
    })