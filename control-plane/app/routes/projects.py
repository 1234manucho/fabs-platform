from flask import (
    Blueprint, render_template, request, redirect, url_for,
    jsonify, current_app, flash,
)
from flask_login import login_required, current_user
from app import db
from app.models import Project, Deployment, EnvVar, Database
from app.payment_gate import paid_required

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
            start_command=request.form.get('start_command', 'gunicorn --bind 0.0.0.0:8000 app:app').strip(),
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
    latest = deployments[0] if deployments else None
    return render_template(
        'project.html', project=project, deployments=deployments, latest=latest
    )


@bp.route('/projects/<int:project_id>/deploy', methods=['POST'])
@login_required
@paid_required
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


@bp.route('/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def delete(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    project_name = project.name
    container_name = project.container_name or f'project-{project.id}'
    pid = project.id

    db.session.delete(project)
    db.session.commit()

    from app.jobs import delete_docker_resources
    current_app.queue.enqueue(
        delete_docker_resources, pid, container_name, job_timeout=120
    )

    flash(f'Project "{project_name}" deleted.')
    return redirect(url_for('main.dashboard'))


@bp.route('/projects/<int:project_id>/env', methods=['POST'])
@login_required
def add_env(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    key = request.form.get('key', '').strip()
    value = request.form.get('value', '')

    if not key or not value:
        flash('Both key and value are required.')
        return redirect(url_for('projects.view', project_id=project.id))

    if not key[0].isalpha() or not key.replace('_', '').replace('-', '').isalnum():
        flash('Key must start with a letter and contain only letters, digits, _ or -.')
        return redirect(url_for('projects.view', project_id=project.id))

    existing = EnvVar.query.filter_by(project_id=project.id, key=key).first()
    if existing:
        existing.value = value
        db.session.commit()
        flash(f'Variable {key} updated. Redeploy to apply.')
    else:
        db.session.add(EnvVar(project_id=project.id, key=key, value=value))
        db.session.commit()
        flash(f'Variable {key} added. Redeploy to apply.')

    return redirect(url_for('projects.view', project_id=project.id))


@bp.route('/projects/<int:project_id>/env/<int:env_id>/delete', methods=['POST'])
@login_required
def delete_env(project_id, env_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()
    ev = EnvVar.query.filter_by(id=env_id, project_id=project.id).first_or_404()
    key = ev.key
    db.session.delete(ev)
    db.session.commit()
    flash(f'Variable {key} deleted. Redeploy to apply.')
    return redirect(url_for('projects.view', project_id=project.id))


@bp.route('/projects/<int:project_id>/databases', methods=['POST'])
@login_required
@paid_required
def create_db(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    name = request.form.get('name', '').strip()
    if not name:
        flash('Database name is required.')
        return redirect(url_for('projects.view', project_id=project.id))

    database = Database(
        project_id=project.id,
        name=name,
        engine='postgres',
        db_name='pending',
        db_user='pending',
        db_password='',
        status='creating',
    )
    db.session.add(database)
    db.session.commit()

    from app.jobs import create_database
    current_app.queue.enqueue(
        create_database, project.id, database.id, job_timeout=180
    )

    flash(f'Database "{name}" is being created. This takes ~10 seconds.')
    return redirect(url_for('projects.view', project_id=project.id))


@bp.route('/databases/<int:database_id>/delete', methods=['POST'])
@login_required
def delete_db(database_id):
    database = Database.query.get_or_404(database_id)
    project = Project.query.filter_by(
        id=database.project_id, user_id=current_user.id
    ).first_or_404()

    name = database.name
    container_name = database.container_name or f'db-{database.id}'
    db_id = database.id

    # Also remove the auto-injected DATABASE_URL env var
    env = EnvVar.query.filter_by(
        project_id=project.id, key='DATABASE_URL'
    ).first()
    if env:
        db.session.delete(env)

    db.session.delete(database)
    db.session.commit()

    from app.jobs import delete_database
    current_app.queue.enqueue(
        delete_database, db_id, container_name, job_timeout=120
    )

    flash(f'Database "{name}" deleted. Redeploy to remove the DATABASE_URL variable.')
    return redirect(url_for('projects.view', project_id=project.id))


@bp.route('/databases/<int:database_id>/connection')
@login_required
def db_connection(database_id):
    database = Database.query.get_or_404(database_id)
    if database.project.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify({
        'url': database.internal_url,
        'host': database.host,
        'port': database.port,
        'user': database.db_user,
        'password': database.db_password,
        'db_name': database.db_name,
    })


@bp.route('/deployments/<int:deployment_id>/logs')
@login_required
def deployment_logs(deployment_id):
    d = Deployment.query.get_or_404(deployment_id)
    if d.project.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify({'status': d.status, 'logs': d.logs or ''})
