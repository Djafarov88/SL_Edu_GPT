import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import (
    ChatMessage,
    ChecklistCompletion,
    Module,
    Notification,
    ROLE_LABELS,
    User,
    UserBadge,
    UserProgress,
    VALID_ROLES,
)
from routes.security import (
    GLOBAL_REPORT_VIEWER_ROLES,
    REPORT_VIEWER_ROLES,
    STORE_ADMIN_ROLES,
    USER_EDITOR_ROLES,
    can_confirm_checklist,
    can_delete_user,
    can_edit_user,
    can_manage_user,
    superadmin_required,
    store_admin_required,
)
from datetime import datetime

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/')
@login_required
@store_admin_required
def index():
    if current_user.role == 'superadmin':
        users = User.query.filter(User.role != 'superadmin').all()
        stores = db.session.query(User.store_name).distinct().all()
        stores = [s[0] for s in stores]
    else:
        users = User.query.filter_by(store_name=current_user.store_name).filter(
            User.role != 'superadmin').all()
        stores = [current_user.store_name]

    total_xp = sum(u.xp_total for u in users)
    level_counts = {}
    for u in users:
        level_counts[u.level] = level_counts.get(u.level, 0) + 1

    if current_user.role == 'superadmin':
        all_progresses = UserProgress.query.all()
    else:
        store_user_ids = {u.id for u in users}
        all_progresses = UserProgress.query.filter(
            UserProgress.user_id.in_(store_user_ids)).all()

    completed_total = sum(1 for p in all_progresses if p.status == 'completed')

    pending_raw = ChecklistCompletion.query.filter_by(confirmed_by_user_id=None).all()
    if current_user.role == 'superadmin':
        pending_checklists = pending_raw
    else:
        pending_checklists = [
            cc for cc in pending_raw
            if User.query.get(cc.user_id) and
               User.query.get(cc.user_id).store_name == current_user.store_name
        ]

    return render_template('admin/index.html', users=users, stores=stores, total_xp=total_xp,
                           level_counts=level_counts, completed_total=completed_total,
                           pending_checklists=pending_checklists)


@admin_bp.route('/users')
@login_required
def users():
    if current_user.role not in set(STORE_ADMIN_ROLES + USER_EDITOR_ROLES):
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('main.dashboard'))

    if current_user.role in USER_EDITOR_ROLES:
        all_users = User.query.filter(User.role != 'superadmin').order_by(
            User.store_name, User.full_name).all()
    else:
        all_users = User.query.filter_by(store_name=current_user.store_name).filter(
            User.role != 'superadmin').order_by(User.full_name).all()

    return render_template('admin/users.html', users=all_users, role_labels=ROLE_LABELS)


@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if not can_edit_user(user):
        flash('Нет прав для редактирования этого пользователя', 'danger')
        logger.warning(
            f'Unauthorized user edit: actor={current_user.username} target={user.username}'
        )
        return redirect(url_for('admin.users'))

    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', user.role)
    store_name = request.form.get('store_name', '').strip()
    job_title = request.form.get('job_title', '').strip()
    department = request.form.get('department', '').strip()
    direction = request.form.get('direction', '').strip()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')

    if not username or not full_name or not store_name:
        flash('Заполните обязательные поля', 'warning')
        return redirect(url_for('admin.users'))

    if role not in VALID_ROLES or role == 'superadmin':
        flash('Недопустимая роль', 'danger')
        return redirect(url_for('admin.users'))

    if current_user.role == 'hr' and role == 'director_retail':
        flash('Нет прав назначать эту роль', 'danger')
        return redirect(url_for('admin.users'))

    duplicate = User.query.filter(User.username == username, User.id != user.id).first()
    if duplicate:
        flash('Пользователь с таким логином уже существует', 'warning')
        return redirect(url_for('admin.users'))

    user.username = username
    user.full_name = full_name
    user.role = role
    user.store_name = store_name
    user.job_title = job_title
    user.department = department
    user.direction = direction
    user.phone = phone
    if password:
        user.set_password(password)

    db.session.commit()
    logger.info(f'User edited: {user.username} by {current_user.username}')
    flash('Пользователь обновлён', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@superadmin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Нельзя удалить самого себя', 'danger')
        return redirect(url_for('admin.users'))

    if user.role in ('superadmin', 'hr'):
        flash('Нельзя удалить ключевую роль', 'danger')
        return redirect(url_for('admin.users'))

    if not can_delete_user(user):
        flash('Нет прав для удаления этого пользователя', 'danger')
        logger.warning(
            f'Unauthorized user delete: actor={current_user.username} target={user.username}'
        )
        return redirect(url_for('admin.users'))

    try:
        username = user.username
        ChecklistCompletion.query.filter_by(confirmed_by_user_id=user.id).update(
            {'confirmed_by_user_id': None}
        )
        ChecklistCompletion.query.filter_by(user_id=user.id).delete()
        UserProgress.query.filter_by(user_id=user.id).delete()
        UserBadge.query.filter_by(user_id=user.id).delete()
        Notification.query.filter_by(user_id=user.id).delete()
        ChatMessage.query.filter_by(user_id=user.id).delete()

        db.session.delete(user)
        db.session.commit()

        logger.info(f'User deleted: {username} by {current_user.username}')
        flash('Пользователь удален', 'success')
    except Exception:
        db.session.rollback()
        logger.exception(
            f'User delete failed: actor={current_user.username} target={user.username}'
        )
        flash('Ошибка при удалении пользователя', 'danger')

    return redirect(url_for('admin.users'))


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@store_admin_required
def create_user():
    if current_user.role != 'superadmin':
        flash('Только суперадмин может создавать пользователей', 'danger')
        return redirect(url_for('admin.users'))

    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'seller')
    store_name = request.form.get('store_name', 'Махачкала').strip()
    job_title = request.form.get('job_title', '').strip()
    department = request.form.get('department', '').strip()
    direction = request.form.get('direction', '').strip()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')

    if not username or not full_name or not password:
        flash('Заполните все обязательные поля', 'warning')
        return redirect(url_for('admin.users'))

    if role not in VALID_ROLES or role == 'superadmin':
        flash('Недопустимая роль', 'danger')
        return redirect(url_for('admin.users'))

    if User.query.filter_by(username=username).first():
        flash('Пользователь с таким логином уже существует', 'warning')
        return redirect(url_for('admin.users'))

    user = User(username=username, full_name=full_name, role=role, store_name=store_name,
                job_title=job_title, department=department, direction=direction, phone=phone)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    logger.info(f'User created: {username} by {current_user.username}')
    flash(f'Сотрудник {full_name} создан!', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@store_admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)

    if not can_manage_user(user):
        flash('Нет прав для управления этим пользователем', 'danger')
        logger.warning(
            f'Unauthorized toggle attempt: actor={current_user.username} target={user.username}'
        )
        return redirect(url_for('admin.users'))

    user.is_active = not user.is_active
    db.session.commit()
    status = 'активирован' if user.is_active else 'деактивирован'
    logger.info(f'User {user.username} {status} by {current_user.username}')
    flash(f'Пользователь {user.full_name} {status}', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/reports')
@login_required
def reports():
    if current_user.role not in REPORT_VIEWER_ROLES:
        flash('Нет доступа к отчетам', 'danger')
        return redirect(url_for('main.index'))

    if current_user.role in GLOBAL_REPORT_VIEWER_ROLES:
        users = User.query.filter(User.role != 'superadmin').all()
    else:
        users = User.query.filter_by(store_name=current_user.store_name).filter(
            User.role != 'superadmin').all()

    modules = Module.query.order_by(Module.order_in_path).all()
    store_user_ids = {u.id for u in users}
    all_progresses = UserProgress.query.filter(
        UserProgress.user_id.in_(store_user_ids)).all() if store_user_ids else []
    prog_map = {(p.user_id, p.module_id): p for p in all_progresses}

    return render_template('admin/reports.html', users=users, modules=modules, prog_map=prog_map)


@admin_bp.route('/checklist/confirm/<int:cc_id>', methods=['POST'])
@login_required
@store_admin_required
def confirm_checklist(cc_id):
    cc = ChecklistCompletion.query.get_or_404(cc_id)

    if not can_confirm_checklist(cc):
        flash('Нет прав для подтверждения этого чеклиста', 'danger')
        logger.warning(
            f'Unauthorized checklist confirm: actor={current_user.username} cc_id={cc_id}'
        )
        return redirect(url_for('admin.index'))

    cc.confirmed_by_user_id = current_user.id
    cc.confirmed_at = datetime.utcnow()

    user = User.query.get(cc.user_id)
    if user:
        user.add_xp(20)
        notif = Notification(
            user_id=user.id,
            text=f'✅ Чеклист модуля «{cc.module.title}» подтверждён! +20 XP'
        )
        db.session.add(notif)

    db.session.commit()
    logger.info(f'Checklist confirmed: cc_id={cc_id} by {current_user.username}')
    flash('Чеклист подтверждён!', 'success')
    return redirect(url_for('admin.index'))
