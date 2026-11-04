from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import Project

bp = Blueprint('main', __name__)

@bp.route('/')
@login_required
def dashboard():
    projects = Project.query.filter_by(user_id=current_user.id)\
        .order_by(Project.created_at.desc()).all()
    stats = {
        'total': len(projects),
        'running': sum(1 for p in projects if p.status == 'running'),
        'failed': sum(1 for p in projects if p.status == 'failed'),
        'deployments': sum(len(p.deployments) for p in projects),
    }
    return render_template('dashboard.html', projects=projects, stats=stats)
