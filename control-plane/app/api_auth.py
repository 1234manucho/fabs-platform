import hashlib
import secrets
from datetime import datetime
from functools import wraps
from flask import request, jsonify, g
from app import db


def generate_api_token():
    """
    Generate a new API token.
    Returns (raw_token, prefix, hash).
    The raw token is shown to the user once and never stored in plaintext.
    """
    raw = 'fabs_' + secrets.token_urlsafe(32)
    prefix = raw[:12]
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, hashed


def hash_token(raw):
    """SHA-256 hash of a raw token string."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _resolve_user():
    """
    Look up the User associated with the incoming request's API token.
    Accepts either:
        Authorization: Bearer fabs_xxxxx
        X-API-Key: fabs_xxxxx
    Returns the User object or None.
    Updates last_used_at on successful auth.
    """
    from app.models import ApiToken, User

    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        raw = auth[7:].strip()
    else:
        raw = request.headers.get('X-API-Key', '').strip()

    if not raw:
        return None

    token = ApiToken.query.filter_by(token_hash=hash_token(raw)).first()
    if not token:
        return None

    token.last_used_at = datetime.utcnow()
    db.session.commit()
    return User.query.get(token.user_id)


def api_token_required(f):
    """Decorator: requires a valid API token. Sets g.api_user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _resolve_user()
        if not user:
            return jsonify({'error': 'invalid_api_token',
                            'hint': 'Provide Authorization: Bearer fabs_xxx'}), 401
        g.api_user = user
        return f(*args, **kwargs)
    return decorated


def api_token_or_admin(f):
    """Decorator: requires a valid API token AND admin privileges."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _resolve_user()
        if not user:
            return jsonify({'error': 'invalid_api_token',
                            'hint': 'Provide Authorization: Bearer fabs_xxx'}), 401
        if not user.is_admin:
            return jsonify({'error': 'admin_required',
                            'hint': 'This endpoint requires admin privileges'}), 403
        g.api_user = user
        return f(*args, **kwargs)
    return decorated
