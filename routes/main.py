from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from extensions import db
from models import User, Module, UserProgress, UserBadge, Notification, LEVEL_LABELS, ROLE_LABELS

main_bp = Blueprint('main', __name__)
GLOBAL_RATING_ROLES = ('superadmin', 'hr', 'director_retail')
RATING_ROLES = ('seller', 'cashier', 'admin_store', 'inventory', 'director')
RATING_MODES = ('all', 'lagging', 'role')


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
    is_global_rating = current_user.role in GLOBAL_RATING_ROLES
    selected_mode = request.args.get('mode', 'all')
    selected_store = request.args.get('store', 'all' if is_global_rating else current_user.store_name)
    selected_role = request.args.get('role', 'all')

    if selected_mode not in RATING_MODES:
        selected_mode = 'all'
    if selected_role != 'all' and selected_role not in RATING_ROLES:
        selected_role = 'all'

    if is_global_rating:
        stores = [
            s[0] for s in db.session.query(User.store_name)
            .filter(User.store_name.isnot(None))
            .distinct()
            .order_by(User.store_name)
            .all()
        ]
        if selected_store != 'all' and selected_store not in stores:
            selected_store = 'all'
    else:
        stores = [current_user.store_name]
        selected_store = current_user.store_name

    users_query = User.query.filter(
        User.role != 'superadmin',
        User.is_active == True
    )

    if is_global_rating:
        if selected_store != 'all':
            users_query = users_query.filter(User.store_name == selected_store)
    else:
        users_query = users_query.filter(User.store_name == current_user.store_name)

    if selected_role != 'all':
        users_query = users_query.filter(User.role == selected_role)

    if selected_mode == 'lagging':
        users = users_query.filter(User.xp_total < 100).order_by(User.xp_total.asc()).all()
    else:
        users = users_query.order_by(User.xp_total.desc()).all()

    roles = [(role, ROLE_LABELS.get(role, role)) for role in RATING_ROLES]

    return render_template(
        'leaderboard.html',
        users=users,
        stores=stores,
        roles=roles,
        current_store=selected_store,
        selected_store=selected_store,
        selected_role=selected_role,
        selected_mode=selected_mode,
        show_all_stores=is_global_rating,
    )


@main_bp.route('/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('main.dashboard'))
