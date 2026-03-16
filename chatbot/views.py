import json
import logging
import traceback
import anthropic

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings

from .models import ChatSession, ChatMessage
from .nigeria_brain import NIGERIA_SYSTEM_PROMPT, SUGGESTED_PROMPTS

logger = logging.getLogger(__name__)


def chatbot_page(request):
    session_id = request.session.get('chat_session_id')
    session = None

    if session_id:
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            pass

    if not session:
        session = ChatSession.objects.create()
        request.session['chat_session_id'] = str(session.session_id)

    history = list(session.messages.values('role', 'content', 'timestamp'))

    context = {
        'session': session,
        'history_json': json.dumps(history, default=str),
        'suggested_prompts': SUGGESTED_PROMPTS,
    }
    return render(request, 'chatbot/chatbot.html', context)


@csrf_exempt
@require_http_methods(['POST'])
def chat_api(request):
    try:
        data = json.loads(request.body)
        user_msg = data.get('message', '').strip()
        session_id = data.get('session_id', '')
        history = data.get('history', [])

        if not user_msg:
            return JsonResponse({'error': 'Empty message'}, status=400)

        # ── 1. Validate API key ──────────────────────────────────
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '').strip()
        if not api_key:
            logger.error("ANTHROPIC_API_KEY is not set in settings / .env")
            return JsonResponse({'error': 'ANTHROPIC_API_KEY missing'}, status=500)

        # ── 2. Load / create DB session ──────────────────────────
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except (ChatSession.DoesNotExist, Exception):
            session = ChatSession.objects.create()

        # ── 3. Save user message ─────────────────────────────────
        ChatMessage.objects.create(session=session, role='user', content=user_msg)

        if session.message_count == 0:
            session.title = user_msg[:60] + ('…' if len(user_msg) > 60 else '')
            session.save()

        # ── 4. Build messages for Claude ─────────────────────────
        messages = []
        for turn in history[-20:]:
            r = turn.get('role', '')
            c = turn.get('content', '')
            if r in ('user', 'assistant') and c:
                messages.append({'role': r, 'content': c})
        messages.append({'role': 'user', 'content': user_msg})

        # ── 5. Streaming generator ────────────────────────────────
        def event_stream():
            full_text = ''
            try:
                client = anthropic.Anthropic(api_key=api_key)

                with client.messages.stream(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=1024,
                    system=NIGERIA_SYSTEM_PROMPT,
                    messages=messages,
                ) as stream:
                    for chunk in stream.text_stream:
                        full_text += chunk
                        yield f'data: {json.dumps({"chunk": chunk})}\n\n'

                # Save completed response
                ChatMessage.objects.create(
                    session=session, role='assistant', content=full_text
                )
                session.message_count += 1
                session.save()

                yield f'data: {json.dumps({"done": True, "session_id": str(session.session_id)})}\n\n'

            except anthropic.AuthenticationError:
                msg = '❌ Your ANTHROPIC_API_KEY is invalid. Check your .env file and restart the server.'
                logger.error(msg)
                yield f'data: {json.dumps({"chunk": msg, "done": True})}\n\n'

            except anthropic.RateLimitError:
                msg = '⚠️ Rate limit reached. Wait a moment and try again.'
                logger.error("Anthropic rate limit hit")
                yield f'data: {json.dumps({"chunk": msg, "done": True})}\n\n'

            except anthropic.APIConnectionError as e:
                msg = '⚠️ Cannot reach the AI service. Check your internet connection.'
                logger.error(f"Connection error: {e}")
                yield f'data: {json.dumps({"chunk": msg, "done": True})}\n\n'

            except Exception as e:
                full_error = traceback.format_exc()
                logger.error(f"Streaming error: {e}\n{full_error}")
                # In DEBUG mode send the real error to the browser so you can see it
                if getattr(settings, 'DEBUG', False):
                    msg = f'⚠️ DEBUG ERROR: {str(e)}'
                else:
                    msg = '⚠️ Something went wrong. Please try again.'
                yield f'data: {json.dumps({"chunk": msg, "done": True})}\n\n'

        return StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"chat_api error: {e}\n{traceback.format_exc()}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def new_session(request):
    session = ChatSession.objects.create()
    request.session['chat_session_id'] = str(session.session_id)
    return JsonResponse({'session_id': str(session.session_id)})


@require_http_methods(['GET'])
def get_history(request, session_id):
    session = get_object_or_404(ChatSession, session_id=session_id)
    messages = list(session.messages.values('role', 'content', 'timestamp'))
    return JsonResponse(
        {'messages': messages, 'title': session.title},
        json_dumps_params={'default': str},
    )