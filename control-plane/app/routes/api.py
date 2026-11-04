from datetime import datetime
from flask import Blueprint, request, jsonify, g, current_app
from app import db
from app.models import User, Project, Deployment, Database, EnvVar
from app.api_auth import api_token_required, api_token_or_admin

bp = Blueprint('api', __name__, url_prefix='/api/v1')


# ============================================================
# PUBLIC ENDPOINTS (no auth)
# ============================================================

@bp.route('/health')
def health():
    """Health check endpoint. Always public."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'service': 'fabs-deploy',
        'version': '0.1.0',
    })


@bp.route('/metrics')
def metrics():
    """Basic platform metrics. Public for monitoring dashboards."""
    return jsonify({
        'users_total': User.query.count(),
        'projects_total': Project.query.count(),
        'projects_running': Project.query.filter_by(status='running').count(),
        'deployments_total': Deployment.query.count(),
        'databases_total': Database.query.count(),
        'databases_running': Database.query.filter_by(status='running').count(),
    })


# ============================================================
# AUTHENTICATED ENDPOINTS (API token required)
# ============================================================

@bp.route('/me')
@api_token_required
def me():
    """Return the authenticated user's profile."""
    u = g.api_user
    return jsonify({
        'id': u.id,
        'email': u.email,
        'plan': u.plan,
        'subscription_status': u.subscription_status,
        'is_admin': u.is_admin,
        'created_at': u.created_at.isoformat() + 'Z',
    })


# ============================================================
# PROJECTS
# ============================================================

@bp.route('/projects', methods=['GET'])
@api_token_required
def list_projects():
    """List all projects owned by the authenticated user."""
    projects = Project.query.filter_by(user_id=g.api_user.id)\
        .order_by(Project.created_at.desc()).all()
    return jsonify([_project(p) for p in projects])


@bp.route('/projects', methods=['POST'])
@api_token_required
def create_project():
    """Create a new project. Requires name, git_url, domain."""
    data = request.get_json(silent=True) or {}

    for field in ('name', 'git_url', 'domain'):
        if not data.get(field):
            return jsonify({'error': 'missing_field', 'field': field}), 400

    domain = data['domain'].strip().lower()

    if Project.query.filter_by(domain=domain).first():
        return jsonify({'error': 'domain_taken',
                        'hint': f'Domain {domain} is already in use'}), 409

    project = Project(
        user_id=g.api_user.id,
        name=data['name'].strip(),
        git_url=data['git_url'].strip(),
        branch=(data.get('branch') or 'main').strip(),
        domain=domain,
        internal_port=int(data.get('internal_port', 8000)),
        start_command=(data.get('start_command') or
                       'gunicorn --bind 0.0.0.0:8000 app:app').strip(),
    )
    db.session.add(project)
    db.session.commit()
    return jsonify(_project(project)), 201


@bp.route('/projects/<int:project_id>', methods=['GET'])
@api_token_required
def get_project(project_id):
    """Get a single project by ID."""
    p = Project.query.filter_by(id=project_id, user_id=g.api_user.id).first()
    if not p:
        return jsonify({'error': 'not_found'}), 404
    return jsonify(_project(p))


@bp.route('/projects/<int:project_id>', methods=['DELETE'])
@api_token_required
def delete_project(project_id):
    """Delete a project and enqueue its Docker cleanup."""
    p = Project.query.filter_by(id=project_id, user_id=g.api_user.id).first()
    if not p:
        return jsonify({'error': 'not_found'}), 404

    pid = p.id
    container = p.container_name or f'project-{p.id}'

    db.session.delete(p)
    db.session.commit()

    from app.jobs import delete_docker_resources
    current_app.queue.enqueue(delete_docker_resources, pid, container, job_timeout=120)

    return jsonify({'deleted': True, 'id': pid}), 200


# ============================================================
# DEPLOYMENTS
# ============================================================

@bp.route('/projects/<int:project_id>/deploy', methods=['POST'])
@api_token_required
def deploy(project_id):
    """Trigger a new deployment for a project."""
    p = Project.query.filter_by(id=project_id, user_id=g.api_user.id).first()
    if not p:
        return jsonify({'error': 'not_found'}), 404

    d = Deployment(project_id=p.id, status='queued')
    db.session.add(d)
    db.session.commit()

    from app.jobs import deploy as deploy_job
    current_app.queue.enqueue(deploy_job, p.id, d.id, job_timeout=900)

    return jsonify({
        'deployment_id': d.id,
        'status': 'queued',
        'logs_url': f'/api/v1/deployments/{d.id}/logs',
    }), 202


@bp.route('/projects/<int:project_id>/deployments', methods=['GET'])
@api_token_required
def list_deployments(project_id):
    """List the last 50 deployments for a project."""
    p = Project.query.filter_by(id=project_id, user_id=g.api_user.id).first()
    if not p:
        return jsonify({'error': 'not_found'}), 404

    rows = Deployment.query.filter_by(project_id=p.id)\
        .order_by(Deployment.created_at.desc()).limit(50).all()

    return jsonify([{
        'id': d.id,
        'status': d.status,
        'created_at': d.created_at.isoformat() + 'Z',
        'finished_at': d.finished_at.isoformat() + 'Z' if d.finished_at else None,
        'logs_url': f'/api/v1/deployments/{d.id}/logs',
    } for d in rows])


@bp.route('/deployments/<int:deployment_id>/logs')
@api_token_required
def deployment_logs(deployment_id):
    """Fetch logs for a specific deployment."""
    d = Deployment.query.get(deployment_id)
    if not d or d.project.user_id != g.api_user.id:
        return jsonify({'error': 'not_found'}), 404
    return jsonify({
        'id': d.id,
        'status': d.status,
        'logs': d.logs or '',
    })


# ============================================================
# ADMIN (token + admin role required)
# ============================================================

@bp.route('/admin/stats')
@api_token_or_admin
def admin_stats():
    """Platform-wide stats. Admin only."""
    pro = User.query.filter_by(plan='pro', subscription_status='active').count()
    return jsonify({
        'users_total': User.query.count(),
        'users_pro': pro,
        'projects_total': Project.query.count(),
        'projects_running': Project.query.filter_by(status='running').count(),
        'deployments_total': Deployment.query.count(),
        'databases_total': Database.query.count(),
        'mrr': pro * 25,
        'arr': pro * 25 * 12,
    })


@bp.route('/admin/users')
@api_token_or_admin
def admin_users():
    """List all users with usage stats. Admin only."""
    users = User.query.order_by(User.created_at.desc()).limit(100).all()
    out = []
    for u in users:
        out.append({
            'id': u.id,
            'email': u.email,
            'plan': u.plan,
            'subscription_status': u.subscription_status,
            'is_admin': u.is_admin,
            'created_at': u.created_at.isoformat() + 'Z',
            'projects_count': Project.query.filter_by(user_id=u.id).count(),
        })
    return jsonify(out)


# ============================================================
# HELPERS
# ============================================================

def _project(p):
    """Serialize a Project for API output."""
    return {
        'id': p.id,
        'name': p.name,
        'git_url': p.git_url,
        'branch': p.branch,
        'domain': p.domain,
        'url': f'https://{p.domain}',
        'internal_port': p.internal_port,
        'start_command': p.start_command,
        'status': p.status,
        'instance_plan': p.instance_plan,
        'created_at': p.created_at.isoformat() + 'Z',
        'deployments_count': len(p.deployments),
        'env_vars_count': len(p.env_vars),
        'databases_count': len(p.databases),
    }
