import logging
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db, limiter
from models import ChatMessage, ROLE_LABELS
import os

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__)

SYSTEM_PROMPT = """Ты — корпоративный наставник компании «Спортлидер» (Дагестан, спортивный ритейл).
Отвечаешь на вопросы сотрудников о продуктах, брендах, технологиях, стандартах работы, этапах продаж и сервисе.
Используй деловой, но дружелюбный тон. Отвечай только по рабочим темам — обучение, продукты, скрипты продаж, регламенты.
Если вопрос личный — мягко верни к рабочей теме.
Отвечай на русском языке. Будь конкретным и практичным.

ВАЖНО: Отвечай обычным текстом без markdown-разметки. Не используй символы **, *, ##, ---, |, или другие специальные символы форматирования. Списки оформляй цифрами или словами, например: "1. Первый пункт", "2. Второй пункт". Для разделения тем используй только переносы строк."""


def _strip_markdown(text):
    import re
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'^-{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-•]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _get_client():
    try:
        import anthropic
        api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('AI_INTEGRATIONS_ANTHROPIC_API_KEY')
        base_url = os.environ.get('AI_INTEGRATIONS_ANTHROPIC_BASE_URL')
        if not api_key:
            return None
        kwargs = {'api_key': api_key}
        if base_url:
            kwargs['base_url'] = base_url
        return anthropic.Anthropic(**kwargs)
    except Exception:
        logger.exception('Failed to initialize Anthropic client')
        return None


@chat_bp.route('/chat')
@login_required
def chat():
    history = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.created_at).all()
    role_label = ROLE_LABELS.get(current_user.role, current_user.role)
    return render_template('chat.html', history=history, role_label=role_label)


@chat_bp.route('/chat/send', methods=['POST'])
@login_required
@limiter.limit("30 per minute; 200 per hour")
def chat_send():
    user_text = request.form.get('message', '').strip()
    if not user_text:
        return jsonify({'error': 'Пустое сообщение'}), 400

    if len(user_text) > 2000:
        return jsonify({'error': 'Сообщение слишком длинное (максимум 2000 символов)'}), 400

    user_msg = ChatMessage(user_id=current_user.id, role='user', content=user_text)
    db.session.add(user_msg)
    db.session.commit()

    history = ChatMessage.query.filter_by(user_id=current_user.id).order_by(
        ChatMessage.created_at.desc()).limit(20).all()
    history.reverse()

    messages = [{'role': m.role, 'content': m.content} for m in history]

    client = _get_client()
    ai_text = ''
    if client:
        try:
            role_label = ROLE_LABELS.get(current_user.role, current_user.role)
            system = (
                f"{SYSTEM_PROMPT}\n\n"
                f"Сотрудник: {current_user.full_name}, "
                f"должность: {role_label}, "
                f"магазин: {current_user.store_name}."
            )
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            ai_text = _strip_markdown(response.content[0].text)
        except Exception:
            logger.exception(f'AI chat error for user={current_user.username}')
            ai_text = 'Ошибка ИИ-ассистента. Попробуйте позже.'
    else:
        ai_text = 'ИИ-ассистент временно недоступен.'

    ai_msg = ChatMessage(user_id=current_user.id, role='assistant', content=ai_text)
    db.session.add(ai_msg)
    db.session.commit()

    return jsonify({'reply': ai_text})


@chat_bp.route('/chat/clear', methods=['POST'])
@login_required
def chat_clear():
    ChatMessage.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'ok': True})
