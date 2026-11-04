from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash,
)
from flask_login import login_required, current_user
from app import db
from app.models import Project, ApiToken
from app.api_auth import generate_api_token

bp = Blueprint('main', __name__)


# ============================================================
# PUBLIC ROUTES
# ============================================================

@bp.route('/')
def home():
    """Root — homepage if logged out, dashboard redirect if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('home.html', preview=False)


@bp.route('/home')
def home_public():
    """Always shows the public homepage, even when logged in."""
    return render_template('home.html', preview=current_user.is_authenticated)


# ============================================================
# AUTHENTICATED ROUTES
# ============================================================

@bp.route('/dashboard')
@login_required
def dashboard():
    """User's project dashboard with aggregated stats."""
    projects = Project.query.filter_by(user_id=current_user.id)\
        .order_by(Project.created_at.desc()).all()
    stats = {
        'total': len(projects),
        'running': sum(1 for p in projects if p.status == 'running'),
        'failed': sum(1 for p in projects if p.status == 'failed'),
        'deployments': sum(len(p.deployments) for p in projects),
    }
    return render_template('dashboard.html', projects=projects, stats=stats)


# ============================================================
# API TOKEN MANAGEMENT
# ============================================================

@bp.route('/settings/tokens', methods=['GET', 'POST'])
@login_required
def settings_tokens():
    """List and create API tokens for the current user."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Token name is required')
            return redirect(url_for('main.settings_tokens'))

        raw, prefix, hashed = generate_api_token()
        db.session.add(ApiToken(
            user_id=current_user.id,
            name=name,
            token_prefix=prefix,
            token_hash=hashed,
        ))
        db.session.commit()
        flash(f'Token created — copy it now, it will not be shown again: {raw}')
        return redirect(url_for('main.settings_tokens'))

    tokens = ApiToken.query.filter_by(user_id=current_user.id)\
        .order_by(ApiToken.created_at.desc()).all()
    return render_template('settings_tokens.html', tokens=tokens)


@bp.route('/settings/tokens/<int:token_id>/delete', methods=['POST'])
@login_required
def delete_token(token_id):
    """Revoke an API token."""
    t = ApiToken.query.filter_by(
        id=token_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Token revoked')
    return redirect(url_for('main.settings_tokens'))
