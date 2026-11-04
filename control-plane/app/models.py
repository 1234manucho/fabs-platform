from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Profile
    name = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    country = db.Column(db.String(2))
    signup_ip = db.Column(db.String(45))

    # Roles & billing
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    stripe_customer_id = db.Column(db.String(255), unique=True, index=True)
    plan = db.Column(db.String(50), default='hobby', nullable=False)
    subscription_status = db.Column(db.String(50), default='inactive', nullable=False)

    projects = db.relationship(
        'Project', backref='owner', lazy=True, cascade='all, delete-orphan'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_paid(self):
        return (
            self.plan in ('basic', 'pro', 'pro_plus', 'ultimate')
            and self.subscription_status == 'active'
        )

    @property
    def is_pro(self):
        # Backwards-compatible alias for old code
        return self.is_paid


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    git_url = db.Column(db.String(500), nullable=False)
    branch = db.Column(db.String(100), default='main')
    domain = db.Column(db.String(255), unique=True, nullable=False)
    internal_port = db.Column(db.Integer, default=8000)
    start_command = db.Column(db.String(255), default='gunicorn --bind 0.0.0.0:8000 app:app')
    container_name = db.Column(db.String(100))
    status = db.Column(db.String(50), default='created')
    instance_plan = db.Column(db.String(50), default='starter', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deployments = db.relationship(
        'Deployment', backref='project', lazy=True, cascade='all, delete-orphan'
    )
    env_vars = db.relationship(
        'EnvVar', backref='project', lazy=True, cascade='all, delete-orphan'
    )
    databases = db.relationship(
        'Database', backref='project', lazy=True, cascade='all, delete-orphan'
    )


class Deployment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    status = db.Column(db.String(50), default='queued')
    logs = db.Column(db.Text, default='')
    image_tag = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)


class EnvVar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('project_id', 'key', name='uix_project_env_key'),
    )


class Database(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    engine = db.Column(db.String(50), default='postgres', nullable=False)
    db_name = db.Column(db.String(100), nullable=False)
    db_user = db.Column(db.String(100), nullable=False)
    db_password = db.Column(db.String(255), nullable=False)
    container_name = db.Column(db.String(100))
    status = db.Column(db.String(50), default='creating')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def internal_url(self):
        return f'postgresql://{self.db_user}:{self.db_password}@{self.container_name}:5432/{self.db_name}'

    @property
    def host(self):
        return self.container_name

    @property
    def port(self):
        return 5432


class ApiToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    token_prefix = db.Column(db.String(20), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_tier = db.Column(db.String(50), nullable=False)
    amount_usd = db.Column(db.Numeric(10, 2), nullable=False)
    amount_local = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(10), default='USD')
    provider = db.Column(db.String(20), nullable=False)  # 'mpesa' or 'dpo'
    provider_ref = db.Column(db.String(255), index=True)  # CheckoutRequestID (M-Pesa) or TransToken (DPO)
    status = db.Column(db.String(50), default='pending')  # pending, success, failed
    raw_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='payments')
