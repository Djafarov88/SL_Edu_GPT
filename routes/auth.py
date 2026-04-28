import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, limiter
from models import User, Notification, Badge, UserBadge, VALID_ROLES
from routes.security import is_safe_redirect_url
from datetime import datetime

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Введите логин и пароль', 'warning')
            return render_template('login.html')

        user = User.query.filter_by(username=username, is_active=True).first()

        if user and user.check_password(password):
            login_user(user, remember=True)
            _grant_welcome_badge(user)
            logger.info(f'Successful login: user={username}')
            flash(f'Добро пожаловать, {user.full_name}!', 'success')

            next_page = request.args.get('next', '')
            if next_page and is_safe_redirect_url(next_page):
                return redirect(next_page)
            return redirect(url_for('main.dashboard'))
        else:
            logger.warning(f'Failed login attempt: username={username!r} ip={request.remote_addr}')
            flash('Неверный логин или пароль', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logger.info(f'Logout: user={current_user.username}')
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role != 'superadmin':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', 'seller')
        store_name = request.form.get('store_name', 'Махачкала').strip()
        password = request.form.get('password', '')

        if not username or not full_name or not password:
            flash('Заполните все поля', 'warning')
        elif role not in VALID_ROLES or role == 'superadmin':
            flash('Недопустимая роль', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует', 'warning')
        else:
            user = User(username=username, full_name=full_name, role=role, store_name=store_name)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'Пользователь {full_name} создан!', 'success')
            return redirect(url_for('admin.users'))

    return render_template('register.html')


def _grant_welcome_badge(user):
    try:
        badge = Badge.query.filter_by(code='welcome').first()
        if badge:
            already = UserBadge.query.filter_by(user_id=user.id, badge_id=badge.id).first()
            if not already:
                ub = UserBadge(user_id=user.id, badge_id=badge.id)
                db.session.add(ub)
                user.add_xp(badge.xp_bonus)
                notif = Notification(
                    user_id=user.id,
                    text=f'🎉 Добро пожаловать в Sportleader Academy! Получен бейдж «{badge.name}»'
                )
                db.session.add(notif)
                db.session.commit()
    except Exception:
        logger.exception('Failed to grant welcome badge')
        db.session.rollback()
