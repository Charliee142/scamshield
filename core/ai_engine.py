# core/ai_engine.py
import base64
import io
import json
import re

import anthropic
from PIL import Image
from django.conf import settings
import re
import json
import base64
import requests
from urllib.parse import urlparse, unquote

import anthropic
from django.conf import settings
from core.models import ScamPattern

import os
import re
import json
import base64
import logging
import anthropic
from django.conf import settings
 
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from AI JSON responses."""
    return re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.MULTILINE).strip()


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP MESSAGE SCANNER
# ══════════════════════════════════════════════════════════════════════════════

URGENCY_WORDS = [
    'immediately', 'urgent', 'today', 'now', 'expire', 'blocked',
    'suspended', 'limited time', 'act now', 'verify now', 'asap',
]
IMPERSONATION_WORDS = [
    'dear customer', 'from the bank', 'zenith bank', 'access bank',
    'gtbank', 'first bank', 'uba', 'fcmb', 'polaris', 'cbn',
    'efcc', 'inec', 'nigerian government', 'nimc', 'frsc',
]
FINANCIAL_BAIT = [
    'win', 'won', 'winner', 'prize', 'award', 'free money',
    'million naira', 'billion', 'investment returns', 'profit',
    'double your money', 'forex', 'crypto profit', 'dividends',
]
THREAT_WORDS = [
    'arrested', 'lawsuit', 'court', 'police', 'prison', 'penalty',
    'fine', 'account blocked', 'deactivated', 'suspended',
]
LINK_PATTERNS = [
    r'http[s]?://', r'bit\.ly', r'tinyurl', r'click here',
    r'www\.', r'\.com/', r'\.net/', r'\.xyz',
]
SENSITIVE_REQUEST = [
    'pin', 'password', 'otp', 'bvn', 'nin', 'account number',
    'card number', 'cvv', 'send money', 'transfer',
]


def analyze_message_locally(message: str) -> dict:
    """Fast rule-based pre-analysis — no API cost."""
    msg_lower = message.lower()
    reasons = []
    confidence = 0

    if any(w in msg_lower for w in URGENCY_WORDS):
        reasons.append("Urgency manipulation detected")
        confidence += 25
    if any(w in msg_lower for w in IMPERSONATION_WORDS):
        reasons.append("Possible bank/government impersonation")
        confidence += 30
    if any(w in msg_lower for w in FINANCIAL_BAIT):
        reasons.append("Unrealistic financial bait")
        confidence += 20
    if any(w in msg_lower for w in THREAT_WORDS):
        reasons.append("Intimidation/threat language")
        confidence += 20
    if any(re.search(p, msg_lower) for p in LINK_PATTERNS):
        reasons.append("Suspicious link or redirect detected")
        confidence += 25
    if any(w in msg_lower for w in SENSITIVE_REQUEST):
        reasons.append("Requests sensitive personal/financial info")
        confidence += 30

    confidence = min(confidence, 95)
    risk = "HIGH" if confidence >= 60 else ("MEDIUM" if confidence >= 30 else "LOW")
    return {"reasons": reasons, "confidence": confidence, "risk": risk}


def get_ai_explanation(message: str, local_result: dict) -> dict:
    """Claude AI deeper analysis — falls back to local result on error."""
    try:
        client = _get_client()
        prompt = f"""You are ScamShield, a Nigerian cybersecurity AI that helps everyday people detect scams.

Analyze this message for scam indicators, especially those common in Nigeria:

MESSAGE:
\"\"\"{message}\"\"\"

Initial analysis detected these issues: {local_result['reasons']}

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "risk_level": "HIGH" or "MEDIUM" or "LOW",
  "confidence": <integer 0-100>,
  "reasons": ["reason 1", "reason 2", "reason 3"],
  "scam_type": "bank_impersonation | investment | lottery | job_scam | romance | phishing | fake_alert | crypto | other",
  "explanation": "2-3 sentences explaining why this is or isn't a scam in simple language any Nigerian can understand",
  "advice": "One clear sentence of advice for the user"
}}"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(_strip_fences(response.content[0].text))

    except Exception as e:
        print(f"[get_ai_explanation] Error: {e}")
        return {
            "risk_level": local_result["risk"],
            "confidence": local_result["confidence"],
            "reasons": local_result["reasons"] or ["Message has unusual patterns"],
            "scam_type": "other",
            "explanation": "This message contains patterns commonly found in scam messages in Nigeria.",
            "advice": "Do not click any links or share personal information from this message.",
        }


def extract_keywords(message: str) -> list:
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
        'to', 'for', 'is', 'it', 'this', 'that', 'are', 'was',
        'will', 'your', 'you', 'we', 'our', 'my', 'from', 'with',
    }
    words = message.lower().split()
    keywords = [w.strip('.,!?;:') for w in words if len(w) > 3 and w not in stop_words]
    return list(set(keywords))[:20]


def update_patterns(scan_result: dict, message: str):
    if scan_result.get('risk_level') != 'HIGH':
        return
    scam_type = scan_result.get('scam_type', 'other')
    keywords = extract_keywords(message)
    pattern, created = ScamPattern.objects.get_or_create(
        scam_type=scam_type,
        defaults={
            'pattern_name': f"Detected {scam_type.replace('_', ' ').title()} Pattern",
            'keywords': keywords,
            'confidence_score': 0.7,
        },
    )
    if not created:
        pattern.keywords = list(set(pattern.keywords) | set(keywords))[:50]
        pattern.occurrence_count += 1
        pattern.confidence_score = min(0.99, pattern.confidence_score + 0.02)
        pattern.save()


def check_learned_patterns(message: str) -> list:
    msg_lower = message.lower()
    matches = []
    for pattern in ScamPattern.objects.filter(is_active=True):
        matched = [k for k in pattern.keywords if k in msg_lower]
        if len(matched) >= 3:
            matches.append({
                'pattern': pattern.pattern_name,
                'scam_type': pattern.scam_type,
                'matched_keywords': matched[:5],
                'confidence': round(pattern.confidence_score * 100),
            })
    return matches


def analyze_whatsapp_message(message: str) -> dict:
    """Main entry point for WhatsApp message analysis."""
    local = analyze_message_locally(message)
    result = get_ai_explanation(message, local)

    pattern_matches = check_learned_patterns(message)
    if pattern_matches:
        result['pattern_matches'] = pattern_matches
        result['emerging_pattern'] = pattern_matches[0]['pattern']

    update_patterns(result, message)
    return result


# ── helper: read image file → base64 + media_type ─────────────────
def _image_to_base64(image_path: str) -> tuple[str, str]:
    """
    Reads an image from disk and returns (base64_string, media_type).
    Supports JPEG, PNG, GIF, WEBP.
    Raises FileNotFoundError if path doesn't exist.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
 
    ext = os.path.splitext(image_path)[1].lower()
    media_type_map = {
        '.jpg':  'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png':  'image/png',
        '.gif':  'image/gif',
        '.webp': 'image/webp',
    }
    media_type = media_type_map.get(ext, 'image/jpeg')
 
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
 
    # Anthropic image size limit is 5 MB
    if len(image_bytes) > 5 * 1024 * 1024:
        raise ValueError("Image is larger than 5 MB. Please upload a smaller screenshot.")
 
    return base64.standard_b64encode(image_bytes).decode('utf-8'), media_type
 
 
# ── extract_text_from_image (OCR — optional, graceful fallback) ────
def extract_text_from_image(image_path: str) -> str:
    """
    Tries Tesseract OCR. If Tesseract is not installed or fails,
    returns an empty string — the caller should still proceed with
    Claude Vision directly rather than aborting.
    """
    try:
        import pytesseract
        from PIL import Image
        import cv2
        import numpy as np
 
        img = cv2.imread(image_path)
        if img is None:
            return ''
 
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Light denoise + threshold to improve OCR on screenshots
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
 
        pil_img = Image.fromarray(thresh)
        text = pytesseract.image_to_string(pil_img, config='--psm 6')
        return text.strip()
 
    except ImportError:
        logger.warning("pytesseract or cv2 not installed — skipping OCR, using Claude Vision only")
        return ''
    except Exception as e:
        logger.warning(f"OCR failed ({e}) — falling back to Claude Vision only")
        return ''
 
 
# ── MAIN FIX: analyze_bank_alert ──────────────────────────────────
def analyze_bank_alert(image_path: str) -> dict:
    """
    Analyzes a bank alert screenshot for fraud indicators.
 
    Strategy:
      1. Send the image DIRECTLY to Claude Vision (base64)
      2. Optionally enrich the prompt with OCR text if available
      3. Parse Claude's JSON response
      4. Return structured result
 
    This completely bypasses the old text-only approach that caused
    the 0% confidence / medium risk fallback.
    """
    # ── Step 1: Load image as base64 ────────────────────────────
    try:
        b64_data, media_type = _image_to_base64(image_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        return _bank_alert_error("Image file not found on server. Please upload again.")
    except ValueError as e:
        logger.error(str(e))
        return _bank_alert_error(str(e))
    except Exception as e:
        logger.error(f"Image read error: {e}")
        return _bank_alert_error("Could not read the uploaded image.")
 
    # ── Step 2: Optional OCR enrichment ─────────────────────────
    ocr_text = extract_text_from_image(image_path)
    ocr_section = ''
    if ocr_text and len(ocr_text) > 10:
        ocr_section = f"\n\nOCR-extracted text from the image:\n```\n{ocr_text[:800]}\n```"
 
    # ── Step 3: Build prompt ─────────────────────────────────────
    prompt = f"""You are ScamShield Nigeria, an expert at detecting fake Nigerian bank alerts.
 
Carefully examine this screenshot and determine if it is a REAL or FAKE bank transaction alert.{ocr_section}
 
Look for these Nigerian bank fraud indicators:
- Sender name that doesn't match official bank format (e.g. "GTBank" vs "Guaranty Trust Bank" vs random names)
- Wrong bank logo, colors, or font compared to the real bank
- Unusual amount formatting (missing commas, wrong naira symbol ₦)
- Suspicious sender numbers or email addresses
- Generic or misspelled words ("Transcation", "Creditted", "Acount")
- Missing transaction reference number
- Non-standard date/time format
- Amount that looks manually typed or edited (pixel inconsistencies)
- Mismatch between currency and bank (e.g. dollar sign on naira bank)
- Pressure language ("Confirm NOW", "expires in 5 minutes")
- The image appears to be an edited screenshot (font inconsistencies, cut-off edges, pixel artifacts)
 
Nigerian banks and their official alert formats:
- GTBank: Sender "GTBank" via SMS, green theme, "Acct" abbreviation
- Zenith Bank: Dark red/maroon, formal language, "ZenithDirect"
- Access Bank: Orange theme, "Access Bank Nigeria"
- First Bank: Blue theme, "FirstBank" sender
- UBA: Red theme, "UBA Nigeria"
- OPay/PalmPay/Kuda: App notification format, NOT SMS
 
Respond ONLY with this exact JSON (no markdown, no extra text):
{{
  "risk_level": "HIGH" or "MEDIUM" or "LOW" or "SAFE",
  "confidence": <integer 0-100>,
  "is_fake": true or false,
  "bank_name": "<detected bank name or 'Unknown'>",
  "amount": "<detected amount or 'Not found'>",
  "reasons": ["<specific reason 1>", "<specific reason 2>"],
  "explanation": "<2-3 plain English sentences a Nigerian can understand>",
  "advice": "<single specific action to take>"
}}"""
 
    # ── Step 4: Call Claude Vision ───────────────────────────────
    try:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '').strip()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
 
        client = anthropic.Anthropic(api_key=api_key)
 
        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=800,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        # ← THIS is the fix: send image as vision block
                        {
                            'type': 'image',
                            'source': {
                                'type':       'base64',
                                'media_type': media_type,
                                'data':       b64_data,
                            },
                        },
                        {
                            'type': 'text',
                            'text': prompt,
                        },
                    ],
                }
            ],
        )
 
        raw = response.content[0].text.strip()
        logger.debug(f"Claude bank alert raw response: {raw}")
 
        # ── Step 5: Parse JSON ───────────────────────────────────
        # Strip markdown fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$',          '', raw, flags=re.MULTILINE)
        raw = raw.strip()
 
        result = json.loads(raw)
 
        # Normalise fields so template always gets expected keys
        return {
            'risk_level':  result.get('risk_level', 'MEDIUM'),
            'confidence':  int(result.get('confidence', 50)),
            'is_fake':     result.get('is_fake', False),
            'bank_name':   result.get('bank_name', 'Unknown'),
            'amount':      result.get('amount', 'Not detected'),
            'reasons':     result.get('reasons', []),
            'explanation': result.get('explanation', ''),
            'advice':      result.get('advice', ''),
            'ocr_text':    ocr_text,
        }
 
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed. Raw Claude output: {raw!r} | Error: {e}")
        # Claude responded but not valid JSON — extract what we can
        return _parse_fallback(raw, ocr_text)
 
    except anthropic.AuthenticationError:
        logger.error("Invalid ANTHROPIC_API_KEY")
        return _bank_alert_error("API key is invalid. Check your .env file.")
 
    except anthropic.RateLimitError:
        logger.error("Anthropic rate limit hit")
        return _bank_alert_error("Too many requests. Wait a moment and try again.")
 
    except Exception as e:
        logger.error(f"analyze_bank_alert error: {e}", exc_info=True)
        return _bank_alert_error(f"Analysis failed: {str(e)}")
 
 
# ── helpers ────────────────────────────────────────────────────────
 
def _bank_alert_error(message: str) -> dict:
    """Returns a structured error result instead of crashing."""
    return {
        'risk_level':  'MEDIUM',
        'confidence':  0,
        'is_fake':     False,
        'bank_name':   'Unknown',
        'amount':      'Not detected',
        'reasons':     [message],
        'explanation': message,
        'advice':      'Please try uploading the image again.',
        'ocr_text':    '',
    }
 
 
def _parse_fallback(raw_text: str, ocr_text: str) -> dict:
    """
    If JSON parsing fails, try to infer result from Claude's plain text.
    This handles cases where Claude returns a conversational answer
    instead of JSON.
    """
    text_lower = raw_text.lower()
    is_fake    = any(w in text_lower for w in ['fake', 'fraudulent', 'scam', 'suspicious', 'not real'])
    is_safe    = any(w in text_lower for w in ['legitimate', 'genuine', 'real', 'authentic', 'looks real'])
 
    if is_fake:
        risk, conf = 'HIGH', 85
    elif is_safe:
        risk, conf = 'SAFE', 80
    else:
        risk, conf = 'MEDIUM', 45
 
    return {
        'risk_level':  risk,
        'confidence':  conf,
        'is_fake':     is_fake,
        'bank_name':   'Unknown',
        'amount':      'Not detected',
        'reasons':     ['AI analysis complete — see explanation below'],
        'explanation': raw_text[:400] if raw_text else 'Could not parse AI response.',
        'advice':      'Verify this alert directly in your bank app or via USSD.',
        'ocr_text':    ocr_text,
    }
 
# ══════════════════════════════════════════════════════════════════════════════
# LINK / URL SCANNER
# ══════════════════════════════════════════════════════════════════════════════
# FIX: Added a broad SAFE_DOMAINS whitelist so google.com and other known-safe
# sites are never flagged. Tightened heuristics so single keywords (like
# "secure") don't trigger a HIGH risk on their own.
# ══════════════════════════════════════════════════════════════════════════════

# ── Domains that are ALWAYS safe — checked first, no further analysis ─────────
SAFE_DOMAINS = {
    # Global tech/services
    "google.com", "google.com.ng", "gmail.com", "youtube.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "whatsapp.com", "telegram.org",
    "microsoft.com", "apple.com", "amazon.com",
    "github.com", "stackoverflow.com",
    "paypal.com", "stripe.com", "flutterwave.com", "paystack.com",
    # Nigerian government
    "efcc.gov.ng", "cbn.gov.ng", "nitda.gov.ng", "nimc.gov.ng",
    "nipost.gov.ng", "ncc.gov.ng", "firs.gov.ng", "frsc.gov.ng",
    "inec.gov.ng", "nnpc.gov.ng",
    # Nigerian banks (official domains)
    "gtbank.com", "guarantytrustbank.com",
    "zenithbank.com",
    "accessbankplc.com", "accessbank.com",
    "firstbanknigeria.com",
    "ubagroup.com",
    "fcmb.com",
    "fidelitybank.ng",
    "stanbicibtcbank.com",
    "polaris.bank",
    "wemabank.com",
    "sterlingbank.ng",
    "keystone.bank",
    "ecobank.com",
    "opay.com",
    "palmpay.com",
    "kudabank.com",
    "moniepoint.com",
}

URL_SHORTENERS = {
    'bit.ly', 'tinyurl.com', 'goo.gl', 'ow.ly', 't.co',
    'short.link', 'rebrand.ly', 'tiny.cc', 'is.gd', 'buff.ly',
    'wa.me', 'lnkd.in', 'cutt.ly', 'shorturl.at', 'rb.gy',
}

SUSPICIOUS_TLDS = {
    '.xyz', '.top', '.click', '.loan', '.win', '.bid',
    '.club', '.site', '.store',
    '.tk', '.ml', '.ga', '.cf', '.gq',
}

# Only flag phishing paths when at least 2 of these appear together
PHISHING_PATH_KEYWORDS = [
    'login', 'signin', 'verify', 'secure', 'account',
    'update', 'confirm', 'suspend', 'blocked', 'urgent',
    'banking', 'password', 'credential', 'otp', 'bvn',
    'transfer', 'payment', 'reward', 'prize',
    'verify-now', 'act-now', 'claim',
]

BANK_LOOKALIKE_KEYWORDS = [
    'gtb', 'gtbank', 'zenith', 'access', 'firstbank',
    'uba', 'fcmb', 'fidelity', 'polaris', 'stanbic',
    'opay', 'palmpay', 'kuda', 'moniepoint',
]


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _extract_base_domain(netloc: str) -> str:
    """Strip www. and return base domain (e.g. 'www.google.com' → 'google.com')."""
    parts = netloc.lower().split('.')
    if parts[0] == 'www' and len(parts) > 2:
        parts = parts[1:]
    # Return last two parts as base domain (handles .com.ng → last 3 parts)
    if len(parts) >= 3 and parts[-2] in ('com', 'gov', 'org', 'edu', 'net', 'co'):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else netloc.lower()


def _check_google_safe_browsing(url: str) -> dict:
    api_key = getattr(settings, 'GOOGLE_SAFE_BROWSING_KEY', None)
    if not api_key:
        return {}
    endpoint = f'https://safebrowsing.googleapis.com/v4/threatMatches:find?key={api_key}'
    payload = {
        'client': {'clientId': 'scamshield-nigeria', 'clientVersion': '1.0'},
        'threatInfo': {
            'threatTypes': ['MALWARE', 'SOCIAL_ENGINEERING', 'UNWANTED_SOFTWARE'],
            'platformTypes': ['ANY_PLATFORM'],
            'threatEntryTypes': ['URL'],
            'threatEntries': [{'url': url}],
        },
    }
    try:
        resp = requests.post(endpoint, json=payload, timeout=5)
        data = resp.json()
        if data.get('matches'):
            match = data['matches'][0]
            return {
                'found': True,
                'threat_type': match.get('threatType', 'PHISHING'),
            }
    except Exception:
        pass
    return {}


def _resolve_redirect(url: str) -> str:
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5)
        return resp.url
    except Exception:
        return url


def analyze_link_rules(url: str) -> dict:
    """
    Fast rule-based link analysis.
    Key fix: SAFE_DOMAINS are whitelisted immediately.
    Heuristics require multiple signals to reach HIGH risk.
    """
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    full_netloc = parsed.netloc.lower()
    base_domain = _extract_base_domain(full_netloc)
    path = unquote((parsed.path + '?' + parsed.query)).lower()
    reasons = []
    confidence = 0

    # ── 1. Safe domain whitelist — bail out immediately ───────────────────────
    if base_domain in SAFE_DOMAINS or full_netloc.lstrip('www.') in SAFE_DOMAINS:
        return {
            'reasons': ['Domain is a verified legitimate website'],
            'confidence': 2,
            'risk': 'SAFE',
            'is_shortener': False,
        }

    # ── 2. URL shortener ──────────────────────────────────────────────────────
    is_shortener = base_domain in URL_SHORTENERS or full_netloc.lstrip('www.') in URL_SHORTENERS
    if is_shortener:
        reasons.append("URL shortener hides the real destination")
        confidence += 20

    # ── 3. Suspicious TLD ─────────────────────────────────────────────────────
    if any(base_domain.endswith(tld) for tld in SUSPICIOUS_TLDS):
        reasons.append(f"Suspicious domain extension (.{base_domain.split('.')[-1]})")
        confidence += 25

    # ── 4. Bank lookalike in domain (but NOT the real domain) ─────────────────
    for bank in BANK_LOOKALIKE_KEYWORDS:
        if bank in base_domain and base_domain not in SAFE_DOMAINS:
            reasons.append(
                f"Domain impersonates '{bank.upper()}' but is NOT the official bank website"
            )
            confidence += 45
            break

    # ── 5. Raw IP address ─────────────────────────────────────────────────────
    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', full_netloc.split(':')[0]):
        reasons.append("URL uses a raw IP address — legitimate banks never do this")
        confidence += 45

    # ── 6. Excessive subdomains ───────────────────────────────────────────────
    subdomain_depth = len(full_netloc.split('.')) - len(base_domain.split('.'))
    if subdomain_depth >= 3:
        reasons.append("Excessive subdomains — classic phishing technique")
        confidence += 20

    # ── 7. Phishing keywords — REQUIRE at least 2 to trigger ─────────────────
    matched_kw = [kw for kw in PHISHING_PATH_KEYWORDS if kw in path or kw in base_domain]
    if len(matched_kw) >= 3:
        reasons.append(f"Multiple phishing keywords in URL: {', '.join(matched_kw[:3])}")
        confidence += 25
    elif len(matched_kw) == 2:
        reasons.append(f"Suspicious URL keywords: {', '.join(matched_kw)}")
        confidence += 15
    # 0 or 1 keyword alone → do NOT add any score

    # ── 8. Hyphenated bank lookalike (e.g. gtbank-secure.com) ────────────────
    if '-' in base_domain:
        for bank in BANK_LOOKALIKE_KEYWORDS:
            if bank in base_domain and base_domain not in SAFE_DOMAINS:
                reasons.append("Hyphenated lookalike domain — common phishing trick")
                confidence += 35
                break

    # ── 9. HTTP only (no TLS) ─────────────────────────────────────────────────
    if parsed.scheme == 'http':
        reasons.append("Not using HTTPS — connection is unencrypted")
        confidence += 15

    # ── 10. Very long URL ─────────────────────────────────────────────────────
    if len(url) > 200:
        reasons.append("Unusually long URL — may be hiding the real destination")
        confidence += 10

    confidence = min(confidence, 97)
    if confidence >= 60:
        risk = 'HIGH'
    elif confidence >= 30:
        risk = 'MEDIUM'
    elif confidence > 0:
        risk = 'LOW'
    else:
        # No flags at all
        risk = 'LOW'
        reasons.append("No obvious red flags — but always verify before entering personal info")

    return {
        'reasons': reasons,
        'confidence': confidence,
        'risk': risk,
        'is_shortener': is_shortener,
    }


def analyze_link_with_ai(url: str, local_result: dict, final_url: str = '') -> dict:
    """Claude AI enrichment for borderline/unclear results."""
    try:
        client = _get_client()
        prompt = f"""You are ScamShield, a Nigerian cybersecurity AI.
Analyze this URL for phishing, scam, or malware risk — especially in the Nigerian context.

URL: {url}
{f'Redirects to: {final_url}' if final_url and final_url != url else ''}
Rule-based flags: {local_result['reasons']}
Rule-based risk: {local_result['risk']} ({local_result['confidence']}% confidence)

IMPORTANT: If this is clearly a legitimate well-known site (Google, Facebook, a real Nigerian bank, etc.)
that was flagged by mistake, correct it to SAFE and explain.

Respond ONLY with valid JSON (no markdown):
{{
  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "SAFE",
  "confidence": <integer 0-100>,
  "reasons": ["clear reason 1", "reason 2"],
  "threat_type": "PHISHING" | "MALWARE" | "SCAM" | "SUSPICIOUS" | "SAFE",
  "explanation": "2-3 plain-English sentences any Nigerian can understand",
  "advice": "one specific action the user should take"
}}"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return json.loads(_strip_fences(response.content[0].text))

    except Exception as e:
        print(f"[analyze_link_with_ai] Error: {e}")
        return {
            'risk_level': local_result['risk'],
            'confidence': local_result['confidence'],
            'reasons': local_result['reasons'] or ['URL could not be fully verified'],
            'threat_type': 'SUSPICIOUS' if local_result['risk'] != 'SAFE' else 'SAFE',
            'explanation': (
                'This link has characteristics sometimes found in phishing URLs. '
                'Always verify before entering personal information.'
            ),
            'advice': 'When in doubt, search for the website directly on Google instead of clicking the link.',
        }


def analyze_url(url: str) -> dict:
    """
    Main entry point for URL analysis.
    Pipeline: whitelist → rules → shortener resolve → Google Safe Browsing → Claude AI
    """
    normalized = _normalize_url(url)

    # Step 1: Rule-based (includes whitelist check)
    local = analyze_link_rules(normalized)

    # Step 2: If whitelisted SAFE, return immediately — no API calls needed
    if local['risk'] == 'SAFE' and local['confidence'] <= 5:
        base = _extract_base_domain(urlparse(normalized).netloc.lower())
        return {
            'risk_level': 'SAFE',
            'confidence': 96,
            'threat_type': 'No Threats Detected',
            'reasons': local['reasons'],
            'explanation': (
                f'{base} is a verified legitimate website. '
                'No threats were detected with this link.'
            ),
            'advice': 'This link appears safe to visit.',
            'is_shortener': False,
            'final_url': normalized,
        }

    # Step 3: Resolve URL shorteners
    final_url = normalized
    if local.get('is_shortener'):
        final_url = _resolve_redirect(normalized)
        # Re-check the resolved domain against safe list
        resolved_base = _extract_base_domain(urlparse(final_url).netloc.lower())
        if resolved_base in SAFE_DOMAINS:
            return {
                'risk_level': 'LOW',
                'confidence': 60,
                'threat_type': 'Shortened URL',
                'reasons': [
                    'Shortened URL used, but destination is a legitimate website',
                    f'Resolves to: {final_url}',
                ],
                'explanation': (
                    'This is a shortened link that leads to a legitimate website. '
                    'Be cautious with shortened links in general as they can hide the real destination.'
                ),
                'advice': 'The destination appears safe, but avoid sharing your personal details unless you are sure.',
                'is_shortener': True,
                'final_url': final_url,
            }

    # Step 4: Google Safe Browsing (authoritative override)
    gsb = _check_google_safe_browsing(normalized)
    if gsb.get('found'):
        return {
            'risk_level': 'HIGH',
            'confidence': 99,
            'threat_type': gsb['threat_type'],
            'reasons': [
                f"⛔ Confirmed by Google Safe Browsing: {gsb['threat_type'].replace('_', ' ').title()}",
            ] + local['reasons'],
            'explanation': (
                'This URL has been confirmed dangerous by Google Safe Browsing — '
                'a global database tracking known phishing and malware sites. '
                'Do NOT visit this link under any circumstances.'
            ),
            'advice': 'Block this contact immediately and report to EFCC at efcc.gov.ng.',
            'is_shortener': local['is_shortener'],
            'final_url': final_url,
        }

    # Step 5: Claude AI enrichment
    ai = analyze_link_with_ai(normalized, local, final_url)
    ai['is_shortener'] = local['is_shortener']
    ai['final_url'] = final_url
    return ai