from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import json


LEVEL_THRESHOLDS = {'start': 0, 'profi': 500, 'master': 1500}
ROLE_OPTIONS = ['seller', 'inventory', 'cashier', 'admin_store', 'director', 'director_retail', 'hr']
VALID_ROLES = ['seller', 'inventory', 'cashier', 'admin_store', 'director', 'director_retail', 'hr', 'superadmin']
LEVEL_LABELS = {'start': 'СТАРТ', 'profi': 'ПРОФИ', 'master': 'МАСТЕР'}
ROLE_LABELS = {
    'seller': 'Продавец-консультант',
    'inventory': 'Продавец инвентаря',
    'cashier': 'Кассир',
    'admin_store': 'Администратор магазина',
    'director': 'Директор магазина',
    'director_retail': 'Розничный директор',
    'hr': 'HR / Специалист по обучению',
    'superadmin': 'Суперадмин',
}


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='seller')
    store_name = db.Column(db.String(100), default='Махачкала')
    job_title = db.Column(db.String(150), default='')
    department = db.Column(db.String(150), default='')
    direction = db.Column(db.String(255), default='')
    phone = db.Column(db.String(30), default='')
    hire_date = db.Column(db.Date, default=date.today)
    xp_total = db.Column(db.Integer, default=0)
    level = db.Column(db.String(20), default='start')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    progresses = db.relationship('UserProgress', backref='user', lazy='dynamic')
    badges = db.relationship('UserBadge', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    chat_messages = db.relationship('ChatMessage', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def add_xp(self, amount):
        self.xp_total += amount
        self._update_level()

    def _update_level(self):
        if self.xp_total >= LEVEL_THRESHOLDS['master']:
            self.level = 'master'
        elif self.xp_total >= LEVEL_THRESHOLDS['profi']:
            self.level = 'profi'
        else:
            self.level = 'start'

    def xp_to_next_level(self):
        if self.level == 'start':
            return LEVEL_THRESHOLDS['profi'] - self.xp_total
        elif self.level == 'profi':
            return LEVEL_THRESHOLDS['master'] - self.xp_total
        return 0

    def level_progress_pct(self):
        if self.level == 'start':
            return min(100, int(self.xp_total / LEVEL_THRESHOLDS['profi'] * 100))
        elif self.level == 'profi':
            gained = self.xp_total - LEVEL_THRESHOLDS['profi']
            needed = LEVEL_THRESHOLDS['master'] - LEVEL_THRESHOLDS['profi']
            return min(100, int(gained / needed * 100))
        return 100

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def level_label(self):
        return LEVEL_LABELS.get(self.level, self.level)

    @property
    def unread_notifications_count(self):
        return self.notifications.filter_by(is_read=False).count()


class Module(db.Model):
    __tablename__ = 'modules'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    level_required = db.Column(db.String(20), default='start')
    duration_minutes = db.Column(db.Integer, default=30)
    xp_reward = db.Column(db.Integer, default=40)
    description = db.Column(db.Text)
    roles_allowed_json = db.Column(db.Text, default='[]')
    order_in_path = db.Column(db.Integer, default=0)

    lessons = db.relationship('Lesson', backref='module', lazy='dynamic', order_by='Lesson.order_in_module')
    test = db.relationship('Test', backref='module', uselist=False)
    checklist_items = db.relationship('ChecklistItem', backref='module', lazy='dynamic', order_by='ChecklistItem.order')

    @property
    def roles_allowed(self):
        try:
            return json.loads(self.roles_allowed_json)
        except Exception:
            return []

    @roles_allowed.setter
    def roles_allowed(self, value):
        self.roles_allowed_json = json.dumps(value)

    @property
    def level_label(self):
        return LEVEL_LABELS.get(self.level_required, self.level_required)

    def is_available_for(self, user):
        levels = ['start', 'profi', 'master']
        user_idx = levels.index(user.level) if user.level in levels else 0
        mod_idx = levels.index(self.level_required) if self.level_required in levels else 0
        return user_idx >= mod_idx and (not self.roles_allowed or user.role in self.roles_allowed or user.role == 'superadmin')


class Lesson(db.Model):
    __tablename__ = 'lessons'
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    order_in_module = db.Column(db.Integer, default=0)
    lesson_type = db.Column(db.String(30), default='theory')


class Test(db.Model):
    __tablename__ = 'tests'
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)
    pass_score_percent = db.Column(db.Integer, default=80)
    max_attempts = db.Column(db.Integer, default=3)
    questions = db.relationship('Question', backref='test', lazy='dynamic')


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), default='single')
    options_json = db.Column(db.Text)
    correct_answer_json = db.Column(db.Text)
    explanation = db.Column(db.Text)
    points = db.Column(db.Integer, default=1)

    @property
    def options(self):
        try:
            return json.loads(self.options_json)
        except Exception:
            return []

    @property
    def correct_answer(self):
        try:
            return json.loads(self.correct_answer_json)
        except Exception:
            return []


class UserProgress(db.Model):
    __tablename__ = 'user_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)
    status = db.Column(db.String(30), default='not_started')
    lessons_read_json = db.Column(db.Text, default='[]')
    test_attempts = db.Column(db.Integer, default=0)
    best_score = db.Column(db.Integer, default=0)
    completed_at = db.Column(db.DateTime)
    xp_earned = db.Column(db.Integer, default=0)

    module = db.relationship('Module')

    @property
    def lessons_read(self):
        try:
            return json.loads(self.lessons_read_json)
        except Exception:
            return []

    @lessons_read.setter
    def lessons_read(self, value):
        self.lessons_read_json = json.dumps(value)

    def lessons_read_count(self):
        return len(self.lessons_read)


class Badge(db.Model):
    __tablename__ = 'badges'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    icon_emoji = db.Column(db.String(10), default='🏅')
    xp_bonus = db.Column(db.Integer, default=0)
    condition_json = db.Column(db.Text, default='{}')

    @property
    def condition(self):
        try:
            return json.loads(self.condition_json)
        except Exception:
            return {}


class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    badge = db.relationship('Badge')


class ChecklistItem(db.Model):
    __tablename__ = 'checklist_items'
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)
    text = db.Column(db.String(300), nullable=False)
    order = db.Column(db.Integer, default=0)


class ChecklistCompletion(db.Model):
    __tablename__ = 'checklist_completions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)
    confirmed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id])
    confirmed_by = db.relationship('User', foreign_keys=[confirmed_by_user_id])
    module = db.relationship('Module')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Position(db.Model):
    __tablename__ = 'positions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.String(255), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
