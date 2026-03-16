# core/whatsapp_bot.py
# ─────────────────────────────────────────────────────────────────────────────
# Place this file inside your  core/  folder.
# It handles every WhatsApp message Twilio sends to your webhook.
#
# Commands users can send:
#   Any text              → scam message analysis
#   LINK <url>            → phishing link scan
#   REPORT <description>  → log a scam report
#   HELP / HI / HELLO     → show menu
# ─────────────────────────────────────────────────────────────────────────────

import logging
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse
from django.conf import settings

from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

# These already exist in your project — no changes needed to ai_engine.py
from core.ai_engine import analyze_whatsapp_message, analyze_url

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SECURITY — verify every request actually came from Twilio
# ══════════════════════════════════════════════════════════════════════════════

def _is_valid_twilio_request(request) -> bool:
    """
    Twilio signs every webhook call with your Auth Token.
    This check prevents anyone else from hitting your endpoint.
    During local ngrok testing comment out the check in whatsapp_webhook()
    if you get 403 errors, then re-enable for production.
    """
    try:
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
        url       = request.build_absolute_uri()
        post_vars = request.POST.dict()
        return validator.validate(url, post_vars, signature)
    except Exception as e:
        logger.error(f"Twilio validation error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTERS — turn AI results into nicely formatted WhatsApp messages
# ══════════════════════════════════════════════════════════════════════════════

def _risk_emoji(risk: str) -> str:
    return {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢', 'SAFE': '✅'}.get(risk.upper(), '⚪')


def _confidence_bar(confidence: int) -> str:
    """Visual bar e.g. ████████░░ 80%"""
    filled = round(confidence / 10)
    return '█' * filled + '░' * (10 - filled)


def format_scan_result(result: dict, original_msg: str) -> str:
    """Format a scam message analysis for WhatsApp."""
    risk      = result.get('risk_level', 'LOW').upper()
    conf      = int(result.get('confidence', 0))
    reasons   = result.get('reasons', [])
    explain   = result.get('explanation', '')
    advice    = result.get('advice', '')
    scam_type = result.get('scam_type', 'other').replace('_', ' ').title()
    echo      = original_msg[:80] + '...' if len(original_msg) > 80 else original_msg

    lines = [
        "🛡️ *ScamShield Nigeria*",
        "",
        f"📩 _{echo}_",
        "",
        f"{_risk_emoji(risk)} *Risk: {risk}*",
        f"📊 {_confidence_bar(conf)} {conf}%",
        f"🏷️ Type: {scam_type}",
        "",
    ]

    if reasons:
        lines.append("🚩 *Red Flags:*")
        for r in reasons[:4]:
            lines.append(f"  • {r}")
        lines.append("")

    if explain:
        lines += [f"💡 {explain}", ""]

    if advice:
        lines += [f"✅ *{advice}*", ""]

    if risk == 'HIGH':
        lines += [
            "🚨 *Report this scam:*",
            "  • EFCC: 0800-326-6722",
            "  • efcc.gov.ng",
            "",
        ]

    lines.append("_Send HELP to see all commands._")
    return '\n'.join(lines)


def format_link_result(result: dict, url: str) -> str:
    """Format a URL scan result for WhatsApp."""
    risk      = result.get('risk_level', 'LOW').upper()
    conf      = int(result.get('confidence', 0))
    reasons   = result.get('reasons', [])
    explain   = result.get('explanation', '')
    advice    = result.get('advice', '')
    threat    = result.get('threat_type', '')
    final_url = result.get('final_url', url)
    short_url = url[:60] + '...' if len(url) > 60 else url

    lines = [
        "🔗 *ScamShield Link Scan*",
        "",
        f"URL: `{short_url}`",
        "",
        f"{_risk_emoji(risk)} *Risk: {risk}*",
        f"📊 {_confidence_bar(conf)} {conf}%",
    ]

    if threat:
        lines.append(f"⚠️ {threat}")

    if result.get('is_shortener') and final_url != url:
        lines.append(f"🔀 Resolves to: {final_url[:70]}")

    lines.append("")

    if reasons:
        lines.append("🚩 *Flags:*")
        for r in reasons[:4]:
            lines.append(f"  • {r}")
        lines.append("")

    if explain:
        lines += [f"💡 {explain}", ""]

    if advice:
        lines += [f"✅ *{advice}*", ""]

    lines.append("_Send LINK <url> to scan another link._")
    return '\n'.join(lines)


def format_help() -> str:
    return (
        "🛡️ *ScamShield Nigeria*\n"
        "AI-Powered Scam Detection — Free\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *How to use me:*\n"
        "\n"
        "1️⃣ *Scan a suspicious message*\n"
        "   Just paste or forward it to me\n"
        "\n"
        "2️⃣ *Scan a suspicious link*\n"
        "   Type: LINK https://example.com\n"
        "\n"
        "3️⃣ *Report a scammer*\n"
        "   Type: REPORT +234XXXXXXXXXX scammed me\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚨 *Emergency Contacts:*\n"
        "  EFCC: 0800-326-6722\n"
        "  GTBank fraud: 0700-482-6000\n"
        "  Zenith fraud: 0700-979-7979\n"
        "  Access fraud: 0700-300-0000\n"
        "\n"
        "_Protecting Nigerians from scams. 🇳🇬_"
    )


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE LOGGING — saves scans to your existing models, no new migrations
# ══════════════════════════════════════════════════════════════════════════════

def _log_message_scan(result: dict, message: str, phone: str):
    try:
        from core.models import ScamScan
        ScamScan.objects.create(
            message_text=message[:500],
            risk_level=result.get('risk_level', 'LOW'),
            confidence=int(result.get('confidence', 0)),
            reasons=result.get('reasons', []),
            ai_explanation=result.get('explanation', ''),
            scam_type=result.get('scam_type', 'other'),
            state='other',
            ip_address=phone,
        )
    except Exception as e:
        logger.warning(f"[WhatsApp] ScamScan log failed: {e}")


def _log_link_scan(result: dict, url: str, phone: str):
    try:
        from core.models import LinkScan
        LinkScan.objects.create(
            url=url[:2000],
            risk_level=result.get('risk_level', 'LOW'),
            confidence=int(result.get('confidence', 0)),
            reasons=result.get('reasons', []),
            threat_type=result.get('threat_type', ''),
            ai_explanation=result.get('explanation', ''),
            is_shortener=result.get('is_shortener', False),
            final_url=result.get('final_url', '')[:2000],
            state='other',
            ip_address=phone,
        )
    except Exception as e:
        logger.warning(f"[WhatsApp] LinkScan log failed: {e}")


def _log_report(text: str, phone: str):
    try:
        from core.models import ScamReport
        ScamReport.objects.create(
            description=text[:1000],
            state='other',
            reporter_contact=phone,
        )
    except Exception as e:
        logger.warning(f"[WhatsApp] ScamReport log failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WEBHOOK — Twilio calls this for every incoming WhatsApp message
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt                     # Twilio cannot send Django's CSRF token
@require_http_methods(['POST'])  # Twilio always uses POST
def whatsapp_webhook(request):
    """
    Twilio calls this URL every time someone sends a WhatsApp message
    to your bot number. We analyze it and reply with TwiML XML.
    """

    # ── Security: confirm request came from Twilio ────────────────────────────
    # DURING LOCAL TESTING: comment out the 3 lines below if you get 403 errors
    # RE-ENABLE before deploying to production
    if not _is_valid_twilio_request(request):
        logger.warning("[WhatsApp] Rejected request with invalid Twilio signature")
        return HttpResponse('Forbidden', status=403)

    # ── Parse incoming fields Twilio sends ────────────────────────────────────
    body        = request.POST.get('Body', '').strip()
    from_number = request.POST.get('From', '')  # e.g. "whatsapp:+2348012345678"

    logger.info(f"[WhatsApp] {from_number}: {body[:80]}")

    # ── Prepare TwiML response ────────────────────────────────────────────────
    twilio_response = MessagingResponse()
    msg             = twilio_response.message()

    # ── Empty message ─────────────────────────────────────────────────────────
    if not body:
        msg.body(format_help())
        return HttpResponse(str(twilio_response), content_type='text/xml')

    upper = body.upper().strip()

    # ── HELP / greeting ───────────────────────────────────────────────────────
    if upper in ('HELP', 'HI', 'HELLO', 'START', 'MENU', 'HEY', 'YO', 'SCAMSHIELD'):
        msg.body(format_help())
        return HttpResponse(str(twilio_response), content_type='text/xml')

    # ── LINK <url> ────────────────────────────────────────────────────────────
    if upper.startswith('LINK '):
        url = body[5:].strip()
        if not url:
            msg.body(
                "Please include the URL after LINK.\n\n"
                "Example:\nLINK https://suspicious-site.com"
            )
        else:
            try:
                result = analyze_url(url)
                msg.body(format_link_result(result, url))
                _log_link_scan(result, url, from_number)
            except Exception as e:
                logger.error(f"[WhatsApp] Link scan error: {e}")
                msg.body(
                    "⚠️ Could not scan that link right now.\n"
                    "Please try again or visit scamshield.ng"
                )
        return HttpResponse(str(twilio_response), content_type='text/xml')

    # ── REPORT <text> ─────────────────────────────────────────────────────────
    if upper.startswith('REPORT '):
        report_text = body[7:].strip()
        if not report_text:
            msg.body(
                "Please describe the scam after REPORT.\n\n"
                "Example:\nREPORT Someone claiming to be GTBank asked for my OTP"
            )
        else:
            _log_report(report_text, from_number)
            msg.body(
                "✅ *Thank you for reporting!*\n\n"
                "Your report is logged and will help protect other Nigerians.\n\n"
                "If you lost money, also contact:\n"
                "  • EFCC: 0800-326-6722\n"
                "  • Your bank's fraud line immediately\n\n"
                "_Every report makes Nigeria safer. 🇳🇬_"
            )
        return HttpResponse(str(twilio_response), content_type='text/xml')

    # ── Very short messages — nudge the user ──────────────────────────────────
    if len(body) < 20:
        msg.body(
            "👋 Hi! I'm ScamShield.\n\n"
            "Forward or paste any suspicious message and I'll analyze it.\n\n"
            "Type *HELP* to see all commands."
        )
        return HttpResponse(str(twilio_response), content_type='text/xml')

    # ── Default: analyze the message as a potential scam ─────────────────────
    try:
        result = analyze_whatsapp_message(body)
        msg.body(format_scan_result(result, body))
        _log_message_scan(result, body, from_number)
    except Exception as e:
        logger.error(f"[WhatsApp] Scan error: {e}")
        msg.body(
            "⚠️ ScamShield is temporarily unavailable.\n\n"
            "Please try again shortly, or visit scamshield.ng\n\n"
            "If urgent, call EFCC: 0800-326-6722"
        )

    return HttpResponse(str(twilio_response), content_type='text/xml')