"""
Reusable permission decorators and helpers for the Academy LMS.

Role hierarchy:
  superadmin    - full access to everything
  hr            - content editor, reports, user editing
  director_retail - content editor, global reports
  director      - store-scoped admin (view and manage own store users)
  admin_store   - store-scoped admin (view and manage own store users)
  seller        - own data only
  inventory     - own data only
  cashier       - own data only
"""
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from urllib.parse import urlparse, urljoin
from flask import request


# ─── Role sets ───────────────────────────────────────────────────────────────

CONTENT_EDITOR_ROLES = ('superadmin', 'hr', 'director_retail')
STORE_ADMIN_ROLES = ('superadmin', 'director', 'admin_store')
REPORT_VIEWER_ROLES = ('superadmin', 'hr', 'director_retail', 'director', 'admin_store')
GLOBAL_REPORT_VIEWER_ROLES = ('superadmin', 'hr', 'director_retail')
USER_EDITOR_ROLES = ('superadmin', 'hr')
USER_DELETER_ROLES = ('superadmin',)
SUPER_ROLES = ('superadmin', 'hr')
ALL_STAFF_ROLES = ('seller', 'inventory', 'cashier', 'admin_store', 'director', 'director_retail', 'hr', 'superadmin')


# ─── Decorators ──────────────────────────────────────────────────────────────

def role_required(*roles):
    """Allow access only to users with one of the given roles."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash('Доступ запрещён', 'danger')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def content_editor_required(f):
    """Allow access only to global content editors."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role not in CONTENT_EDITOR_ROLES:
            flash('Редактирование контента доступно только HR и суперадмину', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def store_admin_required(f):
    """Allow access only to store-level admins and superadmin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role not in STORE_ADMIN_ROLES:
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    """Allow access only to superadmin and HR."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role not in SUPER_ROLES:
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ─── Object-level helpers ─────────────────────────────────────────────────────

def can_manage_user(target_user):
    """
    Return True if the current user is allowed to manage (toggle, view) the target user.
    Rules:
      - superadmin: can manage anyone except other superadmins
      - director/admin_store: can manage only users in their own store, not superadmins
    """
    if not current_user.is_authenticated:
        return False
    if target_user.role == 'superadmin':
        return False
    if current_user.role == 'superadmin':
        return True
    if current_user.role in ('director', 'admin_store'):
        return target_user.store_name == current_user.store_name
    return False


def can_edit_user(target_user):
    """
    Return True if the current user is allowed to edit the target user.
    Rules:
      - superadmin/hr: can edit non-superadmin users
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role not in USER_EDITOR_ROLES:
        return False
    return target_user.role != 'superadmin'


def can_delete_user(target_user):
    """
    Return True if the current user is allowed to delete the target user.
    Rules:
      - only superadmin can delete non-superadmin users
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role not in USER_DELETER_ROLES:
        return False
    return target_user.role != 'superadmin' and target_user.id != current_user.id


def can_confirm_checklist(checklist_completion):
    """
    Return True if current user can confirm a checklist for the target employee.
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role == 'superadmin':
        return True
    if current_user.role in ('director', 'admin_store'):
        from models import User
        target = User.query.get(checklist_completion.user_id)
        return target and target.store_name == current_user.store_name
    return False


# ─── URL validation ───────────────────────────────────────────────────────────

def is_safe_redirect_url(target):
    """
    Validate that a redirect target is a safe local URL (same host).
    Prevents open redirect attacks.
    """
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ('http', 'https') and
        ref_url.netloc == test_url.netloc
    )
