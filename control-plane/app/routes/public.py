from flask import Blueprint, render_template
from flask_login import current_user

bp = Blueprint('public', __name__)


def _preview():
    return current_user.is_authenticated


@bp.route('/pricing')
def pricing():
    return render_template('public/pricing.html', preview=_preview())


@bp.route('/docs')
def docs():
    return render_template('public/docs.html', preview=_preview())
