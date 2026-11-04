import os
import shlex
import shutil
import secrets
import tempfile
import subprocess
import time
from datetime import datetime

import docker

from app.plans import get_plan


def _append(deployment_id, text):
    from app import db
    from app.models import Deployment
    d = Deployment.query.get(deployment_id)
    d.logs = (d.logs or '') + text
    db.session.commit()


def _generate_dockerfile(repo_dir, project):
    cmd = shlex.split(project.start_command or 'python app.py')
    cmd_json = '[' + ', '.join(f'"{c}"' for c in cmd) + ']'

    if os.path.exists(os.path.join(repo_dir, 'requirements.txt')):
        df = f'''FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE {project.internal_port}
CMD {cmd_json}
'''
    elif os.path.exists(os.path.join(repo_dir, 'package.json')):
        df = f'''FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE {project.internal_port}
CMD {cmd_json}
'''
    else:
        raise Exception(
            'Cannot detect project type. Add a Dockerfile to the repo root.'
        )

    with open(os.path.join(repo_dir, 'Dockerfile'), 'w') as f:
        f.write(df)


def _wait_for_tcp(container, port, timeout=45):
    """Poll the container until it accepts TCP connections on `port`."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = container.exec_run(
                cmd=[
                    'python', '-c',
                    'import socket,sys; s=socket.socket(); s.settimeout(2); '
                    f'sys.exit(0 if s.connect_ex(("localhost", {port})) == 0 else 1)'
                ],
            )
            if result.exit_code == 0:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def deploy(project_id, deployment_id):
    from app import create_app, db
    from app.models import Project, Deployment

    app = create_app()
    with app.app_context():
        project = Project.query.get(project_id)
        deployment = Deployment.query.get(deployment_id)

        if project is None or deployment is None:
            return

        workdir = tempfile.mkdtemp(prefix=f'dep-{deployment_id}-')
        repo_dir = os.path.join(workdir, 'repo')

        try:
            deployment.status = 'building'
            db.session.commit()

            _append(deployment_id, f'Cloning {project.git_url} (branch {project.branch})\n')
            r = subprocess.run(
                ['git', 'clone', '--depth', '1', '--branch', project.branch,
                 project.git_url, repo_dir],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise Exception(f'Clone failed: {r.stderr}')
            _append(deployment_id, (r.stderr or '') + '\n')

            if not os.path.exists(os.path.join(repo_dir, 'Dockerfile')):
                _append(deployment_id, 'No Dockerfile found, generating one.\n')
                _generate_dockerfile(repo_dir, project)

            image_tag = f'deploy-{project.id}:{deployment.id}'
            deployment.image_tag = image_tag
            db.session.commit()

            client = docker.from_env()
            _append(deployment_id, f'Building image {image_tag}\n')
            _, build_logs = client.images.build(path=repo_dir, tag=image_tag, rm=True)
            for chunk in build_logs:
                if 'stream' in chunk:
                    _append(deployment_id, chunk['stream'])

            container_name = f'project-{project.id}'
            try:
                old = client.containers.get(container_name)
                _append(deployment_id, f'Stopping old container {container_name}\n')
                old.stop()
                old.remove()
            except docker.errors.NotFound:
                pass

            env_dict = {ev.key: ev.value for ev in project.env_vars}
            if env_dict:
                _append(deployment_id, f'Injecting {len(env_dict)} environment variable(s)\n')
            else:
                _append(deployment_id, 'No environment variables configured\n')

            # Resource limits based on plan tier
            plan = get_plan(project.owner.plan if project.owner else 'hobby')
            mem_mb = plan['memory_mb']
            cpu = plan['cpu_cores']
            _append(deployment_id, f'Plan: {plan["name"]} — {mem_mb}MB RAM, {cpu} vCPU\n')

            _append(deployment_id, 'Starting new container\n')
            container = client.containers.run(
                image_tag,
                detach=True,
                name=container_name,
                environment=env_dict,
                mem_limit=f'{mem_mb}m',
                memswap_limit=f'{mem_mb}m',
                cpu_quota=int(cpu * 100000),
                pids_limit=200,
                security_opt=['no-new-privileges:true'],
                cap_drop=['ALL'],
                labels={
                    'traefik.enable': 'true',
                    f'traefik.http.routers.project-{project.id}.rule':
                        f'Host(`{project.domain}`)',
                    f'traefik.http.routers.project-{project.id}.entrypoints': 'websecure',
                    f'traefik.http.routers.project-{project.id}.tls.certresolver':
                        'letsencrypt',
                    f'traefik.http.services.project-{project.id}.loadbalancer.server.port':
                        str(project.internal_port),
                },
                network=os.getenv('TRAEFIK_NETWORK', 'deploy-platform_traefik'),
                restart_policy={'Name': 'unless-stopped'},
            )

            # Wait for the app to accept connections before marking success
            _append(deployment_id, 'Waiting for app to accept connections...\n')
            ready = _wait_for_tcp(container, project.internal_port, timeout=45)
            if ready:
                _append(deployment_id, '✓ App is healthy and accepting connections.\n')
            else:
                _append(deployment_id, '⚠ App did not respond within 45s. Container is running but may still be initializing.\n')

            project.container_name = container_name
            project.status = 'running'
            deployment.status = 'running'
            deployment.finished_at = datetime.utcnow()
            db.session.commit()
            _append(deployment_id, 'Deployment successful.\n')

        except Exception as e:
            _append(deployment_id, f'\nERROR: {e}\n')
            deployment.status = 'failed'
            project.status = 'failed'
            db.session.commit()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def delete_docker_resources(project_id, container_name):
    try:
        client = docker.from_env()
    except Exception:
        return

    if container_name:
        try:
            c = client.containers.get(container_name)
            try:
                c.stop(timeout=10)
            except Exception:
                pass
            try:
                c.remove(force=True)
            except Exception:
                pass
        except docker.errors.NotFound:
            pass
        except Exception:
            pass

    try:
        prefix = f'deploy-{project_id}:'
        for img in client.images.list():
            for tag in (img.tags or []):
                if tag.startswith(prefix):
                    try:
                        client.images.remove(img.id, force=True)
                    except Exception:
                        pass
    except Exception:
        pass


def create_database(project_id, database_id):
    from app import create_app, db
    from app.models import Project, Database, EnvVar

    app = create_app()
    with app.app_context():
        project = Project.query.get(project_id)
        database = Database.query.get(database_id)
        if not project or not database:
            return

        try:
            client = docker.from_env()
            container_name = f'db-{database.id}'
            volume_name = f'db-volume-{database.id}'

            if not database.db_password:
                database.db_password = secrets.token_urlsafe(24)
                database.db_user = f'user_{database.id}'
                database.db_name = f'db_{database.id}'
                database.container_name = container_name
                db.session.commit()

            try:
                client.volumes.get(volume_name)
            except docker.errors.NotFound:
                client.volumes.create(name=volume_name)

            try:
                old = client.containers.get(container_name)
                old.stop()
                old.remove()
            except docker.errors.NotFound:
                pass

            client.containers.run(
                'postgres:16-alpine',
                detach=True,
                name=container_name,
                environment={
                    'POSTGRES_USER': database.db_user,
                    'POSTGRES_PASSWORD': database.db_password,
                    'POSTGRES_DB': database.db_name,
                },
                volumes={volume_name: {'bind': '/var/lib/postgresql/data', 'mode': 'rw'}},
                network=os.getenv('TRAEFIK_NETWORK', 'deploy-platform_traefik'),
                restart_policy={'Name': 'unless-stopped'},
                mem_limit='512m',
                memswap_limit='512m',
                security_opt=['no-new-privileges:true'],
                labels={
                    'managed-by': 'fabs-platform',
                    f'db-id': str(database.id),
                    f'project-id': str(project.id),
                },
            )

            database.status = 'running'
            db.session.commit()

            conn_str = database.internal_url
            existing = EnvVar.query.filter_by(
                project_id=project.id, key='DATABASE_URL'
            ).first()
            if existing:
                existing.value = conn_str
            else:
                db.session.add(EnvVar(
                    project_id=project.id, key='DATABASE_URL', value=conn_str
                ))
            db.session.commit()

        except Exception as e:
            database.status = 'failed'
            db.session.commit()
            print(f'[db-create] error: {e}')


def delete_database(database_id, container_name):
    try:
        client = docker.from_env()
    except Exception:
        return

    if container_name:
        try:
            c = client.containers.get(container_name)
            try:
                c.stop(timeout=15)
            except Exception:
                pass
            try:
                c.remove(force=True)
            except Exception:
                pass
        except docker.errors.NotFound:
            pass
        except Exception:
            pass

    try:
        volume_name = f'db-volume-{database_id}'
        v = client.volumes.get(volume_name)
        v.remove(force=True)
    except docker.errors.NotFound:
        pass
    except Exception:
        pass


def stop_idle_hobby_containers():
    """
    Stop containers for Hobby users whose apps have been running
    longer than the plan's sleep_after_minutes. Called every minute
    by a cron job. Hobby apps sleep to save resources.

    A user can wake a slept app by clicking Deploy on the project page.
    """
    from app import create_app, db
    from app.models import Project

    app = create_app()
    with app.app_context():
        try:
            client = docker.from_env()
        except Exception:
            return

        now = datetime.utcnow()
        sleep_min = get_plan('hobby')['sleep_after_minutes']
        if not sleep_min:
            return

        stopped_count = 0

        for project in Project.query.filter_by(status='running').all():
            user = project.owner
            if not user or user.plan != 'hobby':
                continue

            container_name = project.container_name or f'project-{project.id}'

            try:
                c = client.containers.get(container_name)
                started_str = c.attrs.get('State', {}).get('StartedAt', '')
                if not started_str:
                    continue

                # Docker returns ISO 8601 UTC like "2026-11-04T12:34:56.789Z"
                started_at = datetime.fromisoformat(
                    started_str.replace('Z', '+00:00')
                ).replace(tzinfo=None)

                idle_seconds = (now - started_at).total_seconds()
                if idle_seconds > sleep_min * 60:
                    c.stop(timeout=10)
                    project.status = 'slept'
                    db.session.commit()
                    stopped_count += 1
                    print(f'[hobby-sleep] stopped {container_name} (idle {int(idle_seconds)}s)')

            except docker.errors.NotFound:
                pass
            except Exception as e:
                print(f'[hobby-sleep] error on {container_name}: {e}')

        if stopped_count:
            print(f'[hobby-sleep] total stopped: {stopped_count}')
