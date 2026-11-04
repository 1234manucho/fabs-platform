import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from redis import Redis
from rq import Queue

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    app.queue = Queue('default', connection=Redis.from_url(os.getenv('REDIS_URL')))

    # Register all blueprints
    from app.routes import (
        public, api, auth, main, projects, webhooks, admin,
    )
    app.register_blueprint(public.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(projects.bp)
    app.register_blueprint(webhooks.bp)
    app.register_blueprint(admin.bp)

    with app.app_context():
        db.create_all()
        from app.migrations import run_migrations
        run_migrations(db)

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return User.query.get(int(user_id))
