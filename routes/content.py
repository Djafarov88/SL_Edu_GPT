import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import Module, Lesson, Test, Question, ChecklistItem, Position, ROLE_LABELS, ROLE_OPTIONS
from routes.security import content_editor_required
import json

logger = logging.getLogger(__name__)
content_bp = Blueprint('content', __name__, url_prefix='/admin/content')

LEVELS = [('start', 'СТАРТ'), ('profi', 'ПРОФИ'), ('master', 'МАСТЕР')]


# ─── Modules ──────────────────────────────────────────────────────────────────

@content_bp.route('/')
@login_required
@content_editor_required
def index():
    modules = Module.query.order_by(Module.order_in_path).all()
    return render_template('admin/content/index.html', modules=modules)


@content_bp.route('/module/new', methods=['GET', 'POST'])
@login_required
@content_editor_required
def module_new():
    if request.method == 'POST':
        roles = request.form.getlist('roles_allowed')
        max_order = db.session.query(db.func.max(Module.order_in_path)).scalar() or 0
        mod = Module(
            code=request.form['code'].strip().upper(),
            title=request.form['title'].strip(),
            description=request.form.get('description', '').strip(),
            category=request.form.get('category', '').strip(),
            level_required=request.form.get('level_required', 'start'),
            duration_minutes=int(request.form.get('duration_minutes', 30)),
            xp_reward=int(request.form.get('xp_reward', 40)),
            order_in_path=int(request.form.get('order_in_path', max_order + 1)),
            roles_allowed_json=json.dumps(roles) if roles else '[]',
        )
        db.session.add(mod)
        db.session.flush()
        test = Test(module_id=mod.id, pass_score_percent=80)
        db.session.add(test)
        db.session.commit()
        logger.info(f'Module created: {mod.code} by {current_user.username}')
        flash(f'Модуль «{mod.title}» создан!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    max_order = db.session.query(db.func.max(Module.order_in_path)).scalar() or 0
    return render_template('admin/content/module_form.html',
                           module=None, levels=LEVELS,
                           role_labels=ROLE_LABELS, role_options=ROLE_OPTIONS,
                           next_order=max_order + 1)


@content_bp.route('/module/<int:module_id>', methods=['GET'])
@login_required
@content_editor_required
def module_detail(module_id):
    mod = Module.query.get_or_404(module_id)
    lessons = mod.lessons.order_by(Lesson.order_in_module).all()
    questions = mod.test.questions.order_by(Question.id).all() if mod.test else []
    checklist = mod.checklist_items.order_by(ChecklistItem.order).all()
    return render_template('admin/content/module_detail.html',
                           mod=mod, lessons=lessons,
                           questions=questions, checklist=checklist,
                           role_labels=ROLE_LABELS)


@content_bp.route('/module/<int:module_id>/edit', methods=['GET', 'POST'])
@login_required
@content_editor_required
def module_edit(module_id):
    mod = Module.query.get_or_404(module_id)
    if request.method == 'POST':
        roles = request.form.getlist('roles_allowed')
        mod.code = request.form['code'].strip().upper()
        mod.title = request.form['title'].strip()
        mod.description = request.form.get('description', '').strip()
        mod.category = request.form.get('category', '').strip()
        mod.level_required = request.form.get('level_required', 'start')
        mod.duration_minutes = int(request.form.get('duration_minutes', 30))
        mod.xp_reward = int(request.form.get('xp_reward', 40))
        mod.order_in_path = int(request.form.get('order_in_path', mod.order_in_path))
        mod.roles_allowed_json = json.dumps(roles) if roles else '[]'
        db.session.commit()
        logger.info(f'Module edited: {mod.code} by {current_user.username}')
        flash('Модуль обновлён!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    return render_template('admin/content/module_form.html',
                           module=mod, levels=LEVELS,
                           role_labels=ROLE_LABELS, role_options=ROLE_OPTIONS,
                           next_order=mod.order_in_path)


@content_bp.route('/module/<int:module_id>/delete', methods=['POST'])
@login_required
@content_editor_required
def module_delete(module_id):
    mod = Module.query.get_or_404(module_id)
    if mod.test:
        Question.query.filter_by(test_id=mod.test.id).delete()
        db.session.delete(mod.test)
    Lesson.query.filter_by(module_id=mod.id).delete()
    ChecklistItem.query.filter_by(module_id=mod.id).delete()
    title = mod.title
    db.session.delete(mod)
    db.session.commit()
    logger.info(f'Module deleted: {title} by {current_user.username}')
    flash(f'Модуль «{title}» удалён.', 'warning')
    return redirect(url_for('content.index'))


# ─── Lessons ──────────────────────────────────────────────────────────────────

@content_bp.route('/module/<int:module_id>/lesson/new', methods=['GET', 'POST'])
@login_required
@content_editor_required
def lesson_new(module_id):
    mod = Module.query.get_or_404(module_id)
    if request.method == 'POST':
        max_order = db.session.query(db.func.max(Lesson.order_in_module)).filter_by(
            module_id=mod.id).scalar() or 0
        lesson = Lesson(
            module_id=mod.id,
            title=request.form['title'].strip(),
            content=request.form.get('content', ''),
            lesson_type=request.form.get('lesson_type', 'theory'),
            order_in_module=int(request.form.get('order_in_module', max_order + 1)),
        )
        db.session.add(lesson)
        db.session.commit()
        flash('Урок добавлен!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    max_order = db.session.query(db.func.max(Lesson.order_in_module)).filter_by(
        module_id=mod.id).scalar() or 0
    return render_template('admin/content/lesson_form.html',
                           mod=mod, lesson=None, next_order=max_order + 1)


@content_bp.route('/lesson/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
@content_editor_required
def lesson_edit(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    mod = lesson.module
    if request.method == 'POST':
        lesson.title = request.form['title'].strip()
        lesson.content = request.form.get('content', '')
        lesson.lesson_type = request.form.get('lesson_type', 'theory')
        lesson.order_in_module = int(request.form.get('order_in_module', lesson.order_in_module))
        db.session.commit()
        flash('Урок сохранён!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    return render_template('admin/content/lesson_form.html',
                           mod=mod, lesson=lesson, next_order=lesson.order_in_module)


@content_bp.route('/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
@content_editor_required
def lesson_delete(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    module_id = lesson.module_id
    db.session.delete(lesson)
    db.session.commit()
    flash('Урок удалён.', 'warning')
    return redirect(url_for('content.module_detail', module_id=module_id))


# ─── Questions ────────────────────────────────────────────────────────────────

@content_bp.route('/module/<int:module_id>/question/new', methods=['GET', 'POST'])
@login_required
@content_editor_required
def question_new(module_id):
    mod = Module.query.get_or_404(module_id)
    if not mod.test:
        test = Test(module_id=mod.id, pass_score_percent=80)
        db.session.add(test)
        db.session.commit()

    if request.method == 'POST':
        options = [
            request.form.get('option_0', '').strip(),
            request.form.get('option_1', '').strip(),
            request.form.get('option_2', '').strip(),
            request.form.get('option_3', '').strip(),
        ]
        options = [o for o in options if o]
        correct_raw = request.form.getlist('correct')
        correct = [int(i) for i in correct_raw if i.isdigit()]

        q = Question(
            test_id=mod.test.id,
            question_text=request.form['question_text'].strip(),
            question_type='single' if len(correct) <= 1 else 'multiple',
            options_json=json.dumps(options, ensure_ascii=False),
            correct_answer_json=json.dumps(correct),
            explanation=request.form.get('explanation', '').strip(),
            points=int(request.form.get('points', 1)),
        )
        db.session.add(q)
        db.session.commit()
        flash('Вопрос добавлен!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    return render_template('admin/content/question_form.html', mod=mod, question=None)


@content_bp.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
@content_editor_required
def question_edit(question_id):
    q = Question.query.get_or_404(question_id)
    mod = q.test.module
    if request.method == 'POST':
        options = [
            request.form.get('option_0', '').strip(),
            request.form.get('option_1', '').strip(),
            request.form.get('option_2', '').strip(),
            request.form.get('option_3', '').strip(),
        ]
        options = [o for o in options if o]
        correct_raw = request.form.getlist('correct')
        correct = [int(i) for i in correct_raw if i.isdigit()]

        q.question_text = request.form['question_text'].strip()
        q.question_type = 'single' if len(correct) <= 1 else 'multiple'
        q.options_json = json.dumps(options, ensure_ascii=False)
        q.correct_answer_json = json.dumps(correct)
        q.explanation = request.form.get('explanation', '').strip()
        q.points = int(request.form.get('points', 1))
        db.session.commit()
        flash('Вопрос обновлён!', 'success')
        return redirect(url_for('content.module_detail', module_id=mod.id))

    options = json.loads(q.options_json) if q.options_json else []
    correct = json.loads(q.correct_answer_json) if q.correct_answer_json else []
    while len(options) < 4:
        options.append('')
    return render_template('admin/content/question_form.html',
                           mod=mod, question=q, options=options, correct=correct)


@content_bp.route('/question/<int:question_id>/delete', methods=['POST'])
@login_required
@content_editor_required
def question_delete(question_id):
    q = Question.query.get_or_404(question_id)
    module_id = q.test.module_id
    db.session.delete(q)
    db.session.commit()
    flash('Вопрос удалён.', 'warning')
    return redirect(url_for('content.module_detail', module_id=module_id))


# ─── Checklist items ──────────────────────────────────────────────────────────

@content_bp.route('/module/<int:module_id>/checklist/add', methods=['POST'])
@login_required
@content_editor_required
def checklist_add(module_id):
    mod = Module.query.get_or_404(module_id)
    text = request.form.get('item_text', '').strip()
    if text:
        max_order = db.session.query(db.func.max(ChecklistItem.order)).filter_by(
            module_id=mod.id).scalar() or 0
        item = ChecklistItem(module_id=mod.id, text=text, order=max_order + 1)
        db.session.add(item)
        db.session.commit()
        flash('Пункт чеклиста добавлен!', 'success')
    return redirect(url_for('content.module_detail', module_id=module_id))


@content_bp.route('/checklist/<int:item_id>/delete', methods=['POST'])
@login_required
@content_editor_required
def checklist_delete(item_id):
    item = ChecklistItem.query.get_or_404(item_id)
    module_id = item.module_id
    db.session.delete(item)
    db.session.commit()
    flash('Пункт удалён.', 'warning')
    return redirect(url_for('content.module_detail', module_id=module_id))


# ─── Positions ────────────────────────────────────────────────────────────────

@content_bp.route('/positions', methods=['GET', 'POST'])
@login_required
@content_editor_required
def positions():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            desc = request.form.get('description', '').strip()
            if name:
                if not Position.query.filter_by(name=name).first():
                    db.session.add(Position(name=name, description=desc))
                    db.session.commit()
                    flash(f'Должность «{name}» добавлена!', 'success')
                else:
                    flash('Такая должность уже есть', 'warning')
        elif action == 'delete':
            pid = request.form.get('position_id')
            if pid and pid.isdigit():
                pos = Position.query.get(int(pid))
                if pos:
                    db.session.delete(pos)
                    db.session.commit()
                    flash('Должность удалена.', 'warning')
        return redirect(url_for('content.positions'))

    all_positions = Position.query.order_by(Position.name).all()
    return render_template('admin/content/positions.html', positions=all_positions)
