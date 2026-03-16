import anthropic
from django.shortcuts import render, redirect
from django.conf import settings
from core.models import ScamScan, ScamReport, ScamPattern
from django.db.models import Count
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.http import FileResponse
import io

import anthropic

def education_coach(request):
    answer = None
    question = ""
    message_context = ""
    error = None

    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        message_context = request.POST.get("message_context", "").strip()

        if question:
            try:
                client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

                system = """You are SABI — ScamShield's AI Education Coach for Nigeria.
Your job is to teach Nigerians about cybersecurity scams in simple, friendly language.
Explain concepts clearly — assume the user is not tech-savvy.
Always end with a practical safety tip specific to Nigeria labeled exactly as: Safety Tip: ..."""

                user_msg = question
                if message_context:
                    user_msg = f"Regarding this message: '{message_context}'\n\nQuestion: {question}"

                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    system=system,
                    messages=[{"role": "user", "content": user_msg}]
                )
                answer = response.content[0].text

            except anthropic.AuthenticationError as e:
                error = "API key is invalid or missing. Check your settings."
                print(f"Auth error: {e}")

            except anthropic.RateLimitError as e:
                error = "Too many requests. Please wait a moment and try again."
                print(f"Rate limit: {e}")

            except anthropic.APIError as e:
                error = f"API error: {str(e)}"
                print(f"API error: {e}")

            except Exception as e:
                error = f"Unexpected error: {str(e)}"
                print(f"Unexpected: {e}")

    return render(request, 'core/education_coach.html', {
        'answer': answer,
        'question': question,
        'message_context': message_context,
        'error': error,
    })

def home(request):
    # Live stats for the homepage
    context = {
        'total_scans': ScamScan.objects.count(),
        'high_risk_scans': ScamScan.objects.filter(risk_level='HIGH').count(),
        'total_reports': ScamReport.objects.count(),
        'patterns_learned': ScamPattern.objects.filter(is_active=True).count(),
        'recent_scans': ScamScan.objects.order_by('-created_at')[:5],
        'top_states': ScamScan.objects.values('state').annotate(
            count=Count('id')).order_by('-count')[:5],
    }
    return render(request, 'core/home.html', context)


def _stats_context():
    """
    Central helper that queries every stat we display on the site.
    Called by home() and dashboard() so the numbers are always identical.
    """
    total_scans       = ScamScan.objects.count()
    high_risk_scans   = ScamScan.objects.filter(risk_level='HIGH').count()
    medium_risk_scans = ScamScan.objects.filter(risk_level='MEDIUM').count()
    low_risk_scans    = ScamScan.objects.filter(risk_level='LOW').count()
    total_reports     = ScamReport.objects.count()
    patterns_learned  = ScamPattern.objects.filter(is_active=True).count()

    # 8 most recent scans (shown in tables / feeds)
    recent_scans = ScamScan.objects.order_by('-created_at')[:8]

    # Top 7 states by scan volume
    top_states = (
        ScamScan.objects
        .values('state')
        .annotate(count=Count('id'))
        .order_by('-count')[:7]
    )

    # Scam-type breakdown (excludes blank scam_type)
    scam_type_breakdown = (
        ScamScan.objects
        .exclude(scam_type='')
        .values('scam_type')
        .annotate(count=Count('id'))
        .order_by('-count')[:7]
    )

    # Community feed and learned patterns
    recent_reports  = ScamReport.objects.order_by('-created_at')[:5]
    active_patterns = (
        ScamPattern.objects
        .filter(is_active=True)
        .order_by('-occurrence_count')[:8]
    )

    return {
        'total_scans':         total_scans,
        'high_risk_scans':     high_risk_scans,
        'medium_risk_scans':   medium_risk_scans,
        'low_risk_scans':      low_risk_scans,
        'total_reports':       total_reports,
        'patterns_learned':    patterns_learned,
        'recent_scans':        recent_scans,
        'top_states':          top_states,
        'scam_type_breakdown': scam_type_breakdown,
        'recent_reports':      recent_reports,
        'active_patterns':     active_patterns,
    }


def dashboard(request):
    """
    Full analytics / intelligence dashboard.

    Extra work done here (beyond _stats_context):
      • Donut chart:   converts raw counts → SVG stroke-dasharray values
                       using circumference of r=36 circle (≈ 226 px)
      • Bar charts:    expresses each row as % of the maximum value so the
                       template can set inline width without any maths
    """
    ctx   = _stats_context()
    total = ctx['total_scans'] or 1          # guard against division-by-zero

    # ── SVG donut calculations ────────────────────────────────────────────────
    CIRC = 226   # 2 * π * 36

    high_pct   = round((ctx['high_risk_scans']   / total) * 100)
    medium_pct = round((ctx['medium_risk_scans'] / total) * 100)
    low_pct    = round((ctx['low_risk_scans']    / total) * 100)

    high_dash   = round((high_pct   / 100) * CIRC, 1)
    medium_dash = round((medium_pct / 100) * CIRC, 1)
    low_dash    = round((low_pct    / 100) * CIRC, 1)

    ctx.update({
        'high_pct':      high_pct,
        'medium_pct':    medium_pct,
        'low_pct':       low_pct,
        'high_dash':     high_dash,
        'medium_dash':   medium_dash,
        'low_dash':      low_dash,
        # negative offsets so each arc begins where the previous one ended
        'medium_offset': -high_dash,
        'low_offset':    -(high_dash + medium_dash),
    })

    # ── Top-state bar chart ───────────────────────────────────────────────────
    top_states_qs = ctx['top_states']
    ctx['top_state'] = top_states_qs[0] if top_states_qs else None

    if top_states_qs:
        max_count = top_states_qs[0]['count']
        ctx['top_states_with_pct'] = [
            {
                'state': s['state'].replace('_', ' ').title(),
                'count': s['count'],
                'pct':   round((s['count'] / max_count) * 100) if max_count else 0,
            }
            for s in top_states_qs
        ]
    else:
        ctx['top_states_with_pct'] = []

    # ── Scam-type bar chart ───────────────────────────────────────────────────
    type_data = list(ctx['scam_type_breakdown'])
    if type_data:
        max_type = type_data[0]['count']
        ctx['scam_type_with_pct'] = [
            {
                'scam_type': t['scam_type'].replace('_', ' ').title(),
                'count':     t['count'],
                'pct':       round((t['count'] / max_type) * 100) if max_type else 0,
            }
            for t in type_data
        ]
    else:
        ctx['scam_type_with_pct'] = []

    return render(request, 'core/dashboard.html', ctx)



def generate_report_pdf(request, scan_id):
    scan = ScamScan.objects.get(id=scan_id)
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    p.setFont("Helvetica-Bold", 20)
    p.drawString(50, 800, "SCAMSHIELD NIGERIA — INCIDENT REPORT")

    p.setFont("Helvetica", 12)
    p.drawString(50, 770, f"Report ID: SS-{scan.id:06d}")
    p.drawString(50, 750, f"Date: {scan.created_at.strftime('%d %B %Y, %H:%M')}")
    p.drawString(50, 730, f"Risk Level: {scan.risk_level}")
    p.drawString(50, 710, f"Confidence: {scan.confidence}%")
    p.drawString(50, 690, f"Scam Type: {scan.scam_type}")

    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, 660, "Evidence (Message Content):")
    p.setFont("Helvetica", 10)

    # Word-wrap the message text
    y = 640
    for line in scan.message_text[:500].split('\n'):
        p.drawString(60, y, line[:100])
        y -= 15

    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y - 20, "AI Analysis:")
    p.setFont("Helvetica", 10)
    p.drawString(60, y - 40, scan.ai_explanation[:200])

    p.drawString(50, 100, "Generated by ScamShield Nigeria | scamshield.ng")
    p.drawString(50, 80,  "This report can be submitted to EFCC: efcc.gov.ng | 0800-326-6722")
    p.save()

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f'scamshield-report-{scan.id}.pdf')