from flask import Blueprint, render_template, abort, request
from flask_login import login_required, current_user
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from app.admin_auth import admin_required
from app.models import User, Project, Deployment, Database, EnvVar

bp = Blueprint('admin', __name__, url_prefix='/admin')


@bp.before_request
@login_required
def require_login():
    if not current_user.is_admin:
        abort(403)


def _mrr():
    """Calculate Monthly Recurring Revenue from active Pro users."""
    pro_count = User.query.filter_by(plan='pro', subscription_status='active').count()
    return pro_count * 25


@bp.route('/')
def dashboard():
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)

    total_users = User.query.count()
    active_subs = User.query.filter_by(subscription_status='active', plan='pro').count()
    free_users = User.query.filter_by(plan='hobby').count()

    total_projects = Project.query.count()
    running_projects = Project.query.filter_by(status='running').count()
    failed_projects = Project.query.filter_by(status='failed').count()

    total_deployments = Deployment.query.count()
    deployments_24h = Deployment.query.filter(Deployment.created_at >= day_ago).count()
    running_deployments = Deployment.query.filter_by(status='running').count()
    failed_deployments = Deployment.query.filter_by(status='failed').count()

    total_databases = Database.query.count()
    running_databases = Database.query.filter_by(status='running').count()

    total_env_vars = EnvVar.query.count()

    recent_users = User.query.order_by(User.created_at.desc()).limit(6).all()
    recent_deployments = Deployment.query.order_by(Deployment.created_at.desc()).limit(6).all()
    recent_databases = Database.query.order_by(Database.created_at.desc()).limit(6).all()

    mrr = _mrr()

    stats = {
        'total_users': total_users,
        'active_subs': active_subs,
        'free_users': free_users,
        'total_projects': total_projects,
        'running_projects': running_projects,
        'failed_projects': failed_projects,
        'total_deployments': total_deployments,
        'deployments_24h': deployments_24h,
        'running_deployments': running_deployments,
        'failed_deployments': failed_deployments,
        'total_databases': total_databases,
        'running_databases': running_databases,
        'total_env_vars': total_env_vars,
        'mrr': mrr,
    }
    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_users=recent_users,
                           recent_deployments=recent_deployments,
                           recent_databases=recent_databases)


@bp.route('/users')
def users():
    q = request.args.get('q', '').strip().lower()
    plan = request.args.get('plan', '')
    status = request.args.get('status', '')

    query = User.query
    if q:
        query = query.filter(User.email.ilike(f'%{q}%'))
    if plan in ('hobby', 'pro'):
        query = query.filter(User.plan == plan)
    if status in ('active', 'inactive', 'past_due'):
        query = query.filter(User.subscription_status == status)

    all_users = query.order_by(User.created_at.desc()).all()

    enriched = []
    for u in all_users:
        enriched.append({
            'user': u,
            'projects': Project.query.filter_by(user_id=u.id).count(),
            'deployments': Deployment.query.join(Project).filter(Project.user_id == u.id).count(),
            'databases': Database.query.join(Project).filter(Project.user_id == u.id).count(),
        })

    return render_template('admin/users.html',
                           rows=enriched, q=q, plan=plan, status=status)


@bp.route('/users/<int:user_id>')
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    projects = Project.query.filter_by(user_id=user.id)\
        .order_by(Project.created_at.desc()).all()

    deployments_count = Deployment.query.join(Project)\
        .filter(Project.user_id == user.id).count()

    db_count = Database.query.join(Project)\
        .filter(Project.user_id == user.id).count()

    env_count = EnvVar.query.join(Project)\
        .filter(Project.user_id == user.id).count()

    running_count = Project.query.filter_by(user_id=user.id, status='running').count()
    failed_count = Project.query.filter_by(user_id=user.id, status='failed').count()

    return render_template('admin/user_detail.html',
                           user=user, projects=projects,
                           deployments_count=deployments_count,
                           db_count=db_count,
                           env_count=env_count,
                           running_count=running_count,
                           failed_count=failed_count)


@bp.route('/projects')
def projects():
    q = request.args.get('q', '').strip().lower()
    query = Project.query
    if q:
        query = query.filter(Project.name.ilike(f'%{q}%'))
    all_projects = query.order_by(Project.created_at.desc()).all()
    return render_template('admin/projects.html', projects=all_projects, q=q)


@bp.route('/deployments')
def deployments():
    status = request.args.get('status', '')
    query = Deployment.query
    if status in ('running', 'failed', 'building', 'queued'):
        query = query.filter(Deployment.status == status)
    rows = query.order_by(Deployment.created_at.desc()).limit(200).all()
    return render_template('admin/deployments.html', deployments=rows, status=status)


@bp.route('/databases')
def databases():
    status = request.args.get('status', '')
    query = Database.query
    if status in ('running', 'creating', 'failed'):
        query = query.filter(Database.status == status)
    rows = query.order_by(Database.created_at.desc()).all()
    return render_template('admin/databases.html', databases=rows, status=status)


@bp.route('/billing')
def billing():
    now = datetime.utcnow()
    month_ago = now - timedelta(days=30)

    active_pro = User.query.filter_by(plan='pro', subscription_status='active').all()
    past_due = User.query.filter_by(subscription_status='past_due').all()
    new_subs_30d = User.query.filter(
        User.plan == 'pro',
        User.subscription_status == 'active',
        User.created_at >= month_ago
    ).count()

    mrr = _mrr()
    arr = mrr * 12

    stats = {
        'mrr': mrr,
        'arr': arr,
        'active_pro': len(active_pro),
        'past_due': len(past_due),
        'new_subs_30d': new_subs_30d,
    }
    return render_template('admin/billing.html', stats=stats,
                           active_pro=active_pro, past_due=past_due)


@bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return ('Cannot remove your own admin rights', 400)
    user.is_admin = not user.is_admin
    from app import db
    db.session.commit()
    return ('ok', 200)
