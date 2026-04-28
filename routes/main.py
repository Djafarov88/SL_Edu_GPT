from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from extensions import db
from models import User, Module, UserProgress, UserBadge, Notification, LEVEL_LABELS

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    user = current_user

    # Get user's modules (filtered by role and level)
    all_modules = Module.query.order_by(Module.order_in_path).all()
    available_modules = [m for m in all_modules if m.is_available_for(user)]

    # Progress for each module
    progresses = {p.module_id: p for p in UserProgress.query.filter_by(user_id=user.id).all()}

    # Next module to study
    next_module = None
    for mod in available_modules:
        prog = progresses.get(mod.id)
        if not prog or prog.status != 'completed':
            next_module = mod
            break

    # Badges
    user_badges = UserBadge.query.filter_by(user_id=user.id).order_by(UserBadge.earned_at.desc()).all()

    # Unread notifications
    notifications = Notification.query.filter_by(user_id=user.id, is_read=False).order_by(Notification.created_at.desc()).limit(5).all()

    # Stats
    completed_count = sum(1 for p in progresses.values() if p.status == 'completed')
    total_available = len(available_modules)

    # Leaderboard position
    store_users = User.query.filter_by(store_name=user.store_name, is_active=True).order_by(User.xp_total.desc()).all()
    my_rank = next((i + 1 for i, u in enumerate(store_users) if u.id == user.id), None)

    return render_template(
        'dashboard.html',
        user=user,
        available_modules=available_modules,
        progresses=progresses,
        next_module=next_module,
        user_badges=user_badges,
        notifications=notifications,
        completed_count=completed_count,
        total_available=total_available,
        my_rank=my_rank,
        store_users_count=len(store_users),
    )


@main_bp.route('/profile')
@login_required
def profile():
    user = current_user
    progresses = UserProgress.query.filter_by(user_id=user.id).order_by(UserProgress.completed_at.desc()).all()
    user_badges = UserBadge.query.filter_by(user_id=user.id).order_by(UserBadge.earned_at.desc()).all()
    total_lessons = sum(p.lessons_read_count() for p in progresses)
    total_tests = sum(p.test_attempts for p in progresses)
    return render_template('profile.html', user=user, progresses=progresses, user_badges=user_badges,
                           total_lessons=total_lessons, total_tests=total_tests)


@main_bp.route('/leaderboard')
@login_required
def leaderboard():
    store_filter = request.args.get('store', current_user.store_name)
    if current_user.role == 'superadmin':
        stores = db.session.query(User.store_name).distinct().all()
        stores = [s[0] for s in stores]
        users = User.query.filter(User.is_active == True, User.role != 'superadmin').filter_by(store_name=store_filter).order_by(User.xp_total.desc()).limit(20).all()
    else:
        stores = [current_user.store_name]
        store_filter = current_user.store_name
        users = User.query.filter_by(store_name=current_user.store_name, is_active=True).filter(User.role != 'superadmin').order_by(User.xp_total.desc()).limit(20).all()

    return render_template('leaderboard.html', users=users, stores=stores, current_store=store_filter)


@main_bp.route('/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('main.dashboard'))
