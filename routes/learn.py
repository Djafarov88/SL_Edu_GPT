import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Module, Lesson, UserProgress, Test, Question, Badge, UserBadge, Notification, ChecklistItem, ChecklistCompletion
from datetime import datetime
import json, random

logger = logging.getLogger(__name__)
learn_bp = Blueprint('learn', __name__)


def _get_or_create_progress(user_id, module_id):
    prog = UserProgress.query.filter_by(user_id=user_id, module_id=module_id).first()
    if not prog:
        prog = UserProgress(user_id=user_id, module_id=module_id, status='not_started')
        db.session.add(prog)
        db.session.commit()
    return prog


@learn_bp.route('/learn')
@login_required
def learn():
    all_modules = Module.query.order_by(Module.order_in_path).all()
    available = [m for m in all_modules if m.is_available_for(current_user)]
    locked = [m for m in all_modules if not m.is_available_for(current_user)]
    progresses = {p.module_id: p for p in UserProgress.query.filter_by(user_id=current_user.id).all()}
    categories = list(dict.fromkeys(m.category for m in available if m.category))
    filter_cat = request.args.get('category', '')
    if filter_cat:
        available = [m for m in available if m.category == filter_cat]
    return render_template('learn.html', available=available, locked=locked, progresses=progresses,
                           categories=categories, filter_cat=filter_cat)


@learn_bp.route('/learn/<code>')
@login_required
def module_view(code):
    module = Module.query.filter_by(code=code).first_or_404()
    if not module.is_available_for(current_user):
        flash('Модуль недоступен для вашего уровня или роли', 'warning')
        return redirect(url_for('learn.learn'))
    prog = _get_or_create_progress(current_user.id, module.id)
    lessons = module.lessons.order_by(Lesson.order_in_module).all()
    checklist = module.checklist_items.order_by(ChecklistItem.order).all()
    checklist_done = ChecklistCompletion.query.filter_by(
        user_id=current_user.id, module_id=module.id).first()
    all_lessons_read = len(prog.lessons_read) >= len(lessons) if lessons else True
    return render_template('module.html', module=module, prog=prog, lessons=lessons,
                           checklist=checklist, checklist_done=checklist_done,
                           all_lessons_read=all_lessons_read)


@learn_bp.route('/learn/<code>/lesson/<int:lesson_id>/complete', methods=['POST'])
@login_required
def complete_lesson(code, lesson_id):
    module = Module.query.filter_by(code=code).first_or_404()

    if not module.is_available_for(current_user):
        flash('Модуль недоступен', 'warning')
        return redirect(url_for('learn.learn'))

    lesson = Lesson.query.get_or_404(lesson_id)

    if lesson.module_id != module.id:
        logger.warning(
            f'Lesson/module mismatch: user={current_user.username} '
            f'lesson_id={lesson_id} module_code={code}'
        )
        flash('Ошибка: урок не принадлежит данному модулю', 'danger')
        return redirect(url_for('learn.module_view', code=code))

    prog = _get_or_create_progress(current_user.id, module.id)

    read = prog.lessons_read
    if lesson_id not in read:
        read.append(lesson_id)
        prog.lessons_read = read
        if prog.status == 'not_started':
            prog.status = 'in_progress'

        current_user.add_xp(10)
        notif = Notification(user_id=current_user.id, text=f'📖 +10 XP за урок «{lesson.title}»')
        db.session.add(notif)
        db.session.commit()

    return redirect(url_for('learn.module_view', code=code))


@learn_bp.route('/learn/<code>/test', methods=['GET'])
@login_required
def test_view(code):
    module = Module.query.filter_by(code=code).first_or_404()

    if not module.is_available_for(current_user):
        flash('Модуль недоступен', 'warning')
        return redirect(url_for('learn.learn'))

    test = module.test
    if not test:
        flash('У этого модуля нет теста', 'info')
        return redirect(url_for('learn.module_view', code=code))

    prog = _get_or_create_progress(current_user.id, module.id)
    lessons = module.lessons.all()
    if len(prog.lessons_read) < len(lessons):
        flash('Сначала прочитайте все уроки модуля', 'warning')
        return redirect(url_for('learn.module_view', code=code))

    if prog.test_attempts >= test.max_attempts:
        flash(f'Достигнуто максимальное количество попыток ({test.max_attempts})', 'danger')
        return redirect(url_for('learn.module_view', code=code))

    questions = list(test.questions.all())
    random.shuffle(questions)
    return render_template('test.html', module=module, test=test, questions=questions, prog=prog)


@learn_bp.route('/learn/<code>/test/submit', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def test_submit(code):
    module = Module.query.filter_by(code=code).first_or_404()

    if not module.is_available_for(current_user):
        flash('Модуль недоступен', 'warning')
        return redirect(url_for('learn.learn'))

    test = module.test
    if not test:
        return redirect(url_for('learn.module_view', code=code))

    prog = _get_or_create_progress(current_user.id, module.id)

    if prog.test_attempts >= test.max_attempts:
        logger.warning(
            f'Attempted test submission beyond max attempts: '
            f'user={current_user.username} module={code}'
        )
        flash('Достигнуто максимальное количество попыток', 'danger')
        return redirect(url_for('learn.module_view', code=code))

    questions = list(test.questions.all())
    total = len(questions)
    correct = 0
    results = []

    for q in questions:
        user_answer = request.form.getlist(f'q_{q.id}')
        user_ints = sorted([int(x) for x in user_answer if x.isdigit()])
        correct_ans = sorted(q.correct_answer)
        is_correct = user_ints == correct_ans
        if is_correct:
            correct += 1
        results.append({
            'question': q.question_text,
            'indexed_options': list(enumerate(q.options)),
            'user_answer': user_ints,
            'correct_answer': correct_ans,
            'is_correct': is_correct,
            'explanation': q.explanation,
        })

    score_pct = int(correct / total * 100) if total > 0 else 0
    prog.test_attempts += 1
    first_attempt = prog.test_attempts == 1

    if score_pct > prog.best_score:
        prog.best_score = score_pct

    passed = score_pct >= test.pass_score_percent

    if passed:
        test_xp = 80 if (score_pct >= 90 and first_attempt) else 30
        notif_parts = [f'✅ +{test_xp} XP за тест «{module.title}» ({score_pct}%)']
        current_user.add_xp(test_xp)

        if prog.status != 'completed':
            prog.status = 'completed'
            prog.completed_at = datetime.utcnow()
            prog.xp_earned = test_xp + module.xp_reward
            current_user.add_xp(module.xp_reward)
            notif_parts.append(f'+{module.xp_reward} XP за завершение модуля!')
            _check_badges(current_user, module)

        notif = Notification(user_id=current_user.id, text=' '.join(notif_parts))
        db.session.add(notif)
    else:
        notif = Notification(
            user_id=current_user.id,
            text=f'❌ Тест «{module.title}» не пройден ({score_pct}%). Нужно {test.pass_score_percent}%.'
        )
        db.session.add(notif)

    db.session.commit()
    return render_template('test_result.html', module=module, score_pct=score_pct, passed=passed,
                           correct=correct, total=total, results=results, prog=prog,
                           pass_score=test.pass_score_percent)


@learn_bp.route('/checklist/<code>')
@login_required
def checklist_view(code):
    module = Module.query.filter_by(code=code).first_or_404()
    if not module.is_available_for(current_user):
        flash('Модуль недоступен', 'warning')
        return redirect(url_for('learn.learn'))
    items = module.checklist_items.order_by(ChecklistItem.order).all()
    done = ChecklistCompletion.query.filter_by(
        user_id=current_user.id, module_id=module.id).first()
    pending = ChecklistCompletion.query.filter_by(
        user_id=current_user.id, module_id=module.id, confirmed_by_user_id=None).first()
    return render_template('checklist.html', module=module, items=items, done=done, pending=pending)


@learn_bp.route('/checklist/<code>/request', methods=['POST'])
@login_required
def checklist_request(code):
    module = Module.query.filter_by(code=code).first_or_404()
    if not module.is_available_for(current_user):
        flash('Модуль недоступен', 'warning')
        return redirect(url_for('learn.learn'))
    existing = ChecklistCompletion.query.filter_by(
        user_id=current_user.id, module_id=module.id).first()
    if not existing:
        cc = ChecklistCompletion(user_id=current_user.id, module_id=module.id)
        db.session.add(cc)
        db.session.commit()
        flash('Запрос отправлен администратору на подтверждение', 'success')
    return redirect(url_for('learn.checklist_view', code=code))


def _check_badges(user, module):
    badge_map = {
        'M001': 'dna',
        'M003': 'brands',
        'M004': 'technologist',
        'M005': 'combat_expert',
    }
    badge_code = badge_map.get(module.code)
    if badge_code:
        _award_badge(user, badge_code)
    if user.level == 'master':
        _award_badge(user, 'mentor')


def _award_badge(user, badge_code):
    try:
        badge = Badge.query.filter_by(code=badge_code).first()
        if not badge:
            return
        already = UserBadge.query.filter_by(user_id=user.id, badge_id=badge.id).first()
        if not already:
            ub = UserBadge(user_id=user.id, badge_id=badge.id)
            db.session.add(ub)
            user.add_xp(badge.xp_bonus)
            notif = Notification(
                user_id=user.id,
                text=f'🏅 Получен бейдж «{badge.name}»! +{badge.xp_bonus} XP'
            )
            db.session.add(notif)
    except Exception:
        logger.exception(f'Failed to award badge {badge_code} to user {user.id}')
