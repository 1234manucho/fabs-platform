import hmac
import hashlib
import os
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import Project, Deployment

bp = Blueprint('webhooks', __name__)


def _normalize_repo(url: str) -> str:
    if not url:
        return ''
    url = url.strip().rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]
    return url.lower()


@bp.route('/api/github/webhook', methods=['POST'])
def github_webhook():
    secret = os.getenv('GITHUB_WEBHOOK_SECRET')
    if not secret:
        return jsonify({'error': 'webhook secret not configured'}), 500

    signature = request.headers.get('X-Hub-Signature-256', '')
    if not signature.startswith('sha256='):
        return jsonify({'error': 'invalid signature header'}), 401

    raw = request.get_data()
    expected = 'sha256=' + hmac.new(
        secret.encode(), raw, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return jsonify({'error': 'signature mismatch'}), 401

    event = request.headers.get('X-GitHub-Event')
    if event == 'ping':
        return jsonify({'ok': True, 'msg': 'pong'})
    if event != 'push':
        return jsonify({'ok': True, 'msg': f'ignored event {event}'})

    payload = request.get_json(silent=True) or {}
    ref = payload.get('ref', '')
    if not ref.startswith('refs/heads/'):
        return jsonify({'ok': True, 'msg': 'not a branch push'})
    branch = ref.replace('refs/heads/', '', 1)

    repo = payload.get('repository', {})
    clone_url = _normalize_repo(repo.get('clone_url') or '')
    html_url = _normalize_repo(repo.get('html_url') or '')
    ssh_url = _normalize_repo(repo.get('ssh_url') or '')

    matched = []
    for project in Project.query.all():
        if project.branch != branch:
            continue
        p_url = _normalize_repo(project.git_url)
        if p_url in (clone_url, html_url, ssh_url):
            matched.append(project)

    if not matched:
        return jsonify({'ok': True, 'msg': 'no matching project'}), 202

    for project in matched:
        deployment = Deployment(project_id=project.id, status='queued')
        db.session.add(deployment)
        db.session.commit()
        from app.jobs import deploy as deploy_job
        current_app.queue.enqueue(
            deploy_job, project.id, deployment.id, job_timeout=900
        )

    return jsonify({'ok': True, 'deployed': [p.id for p in matched]})