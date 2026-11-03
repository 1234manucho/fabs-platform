from flask import (
    Blueprint, render_template, request, redirect, url_for,
    jsonify, current_app,
)
from flask_login import login_required, current_user
from app import db
from app.models import Project, Deployment

bp = Blueprint('projects', __name__)


@bp.route('/projects/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        project = Project(
            user_id=current_user.id,
            name=request.form['name'].strip(),
            git_url=request.form['git_url'].strip(),
            branch=request.form.get('branch', 'main').strip() or 'main',
            domain=request.form['domain'].strip().lower(),
            internal_port=int(request.form.get('internal_port', 8000)),
            start_command=request.form.get('start_command', 'python app.py').strip(),
        )
        db.session.add(project)
        db.session.commit()
        return redirect(url_for('projects.view', project_id=project.id))
    return render_template('new_project.html')


@bp.route('/projects/<int:project_id>')
@login_required
def view(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()
    deployments = Deployment.query.filter_by(project_id=project.id)\
        .order_by(Deployment.created_at.desc()).all()
    return render_template(
        'project.html', project=project, deployments=deployments
    )


@bp.route('/projects/<int:project_id>/deploy', methods=['POST'])
@login_required
def deploy(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()
    deployment = Deployment(project_id=project.id, status='queued')
    db.session.add(deployment)
    db.session.commit()

    from app.jobs import deploy as deploy_job
    current_app.queue.enqueue(
        deploy_job, project.id, deployment.id, job_timeout=900
    )
    return jsonify({'deployment_id': deployment.id})


@bp.route('/deployments/<int:deployment_id>/logs')
@login_required
def deployment_logs(deployment_id):
    d = Deployment.query.get_or_404(deployment_id)
    if d.project.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify({'status': d.status, 'logs': d.logs or ''})