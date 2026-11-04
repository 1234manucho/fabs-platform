from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, session,
)
from flask_login import login_required, current_user
from app import db
from app.models import Project, ApiToken
from app.api_auth import generate_api_token

bp = Blueprint('main', __name__)


@bp.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('home.html', preview=False)


@bp.route('/home')
def home_public():
    return render_template('home.html', preview=current_user.is_authenticated)


@bp.route('/dashboard')
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


@bp.route('/settings/tokens', methods=['GET', 'POST'])
@login_required
def settings_tokens():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Token name is required')
            return redirect(url_for('main.settings_tokens'))

        raw, prefix, hashed = generate_api_token()
        token = ApiToken(
            user_id=current_user.id,
            name=name,
            token_prefix=prefix,
            token_hash=hashed,
        )
        db.session.add(token)
        db.session.commit()

        # FIX: Store raw token in session for one-time display instead of flash
        session[f'new_token_{token.id}'] = raw
        return redirect(url_for('main.token_created', token_id=token.id))

    tokens = ApiToken.query.filter_by(user_id=current_user.id)\
        .order_by(ApiToken.created_at.desc()).all()
    return render_template('settings_tokens.html', tokens=tokens)


@bp.route('/settings/tokens/<int:token_id>/created')
@login_required
def token_created(token_id):
    """One-time token display. Raw token is popped from session — shows exactly once."""
    token = ApiToken.query.filter_by(
        id=token_id, user_id=current_user.id
    ).first_or_404()
    raw = session.pop(f'new_token_{token_id}', None)
    if not raw:
        flash('Token already shown. Create a new one if you need it.')
        return redirect(url_for('main.settings_tokens'))
    return render_template('settings_token_created.html', token=token, raw=raw)


@bp.route('/settings/tokens/<int:token_id>/delete', methods=['POST'])
@login_required
def delete_token(token_id):
    t = ApiToken.query.filter_by(
        id=token_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Token revoked')
    return redirect(url_for('main.settings_tokens'))
