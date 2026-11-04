import click
from flask.cli import with_appcontext


def register_cli(app):
    """Register all Flask CLI commands on the app."""

    @app.cli.command('create-admin')
    @click.argument('email')
    @click.argument('password')
    @with_appcontext
    def create_admin(email, password):
        """Create a new admin user.

        Usage: flask --app run:app create-admin EMAIL PASSWORD
        """
        from app import db
        from app.models import User

        email = email.strip().lower()

        if len(password) < 8:
            click.echo('ERROR: Password must be at least 8 characters.', err=True)
            return

        if User.query.filter_by(email=email).first():
            click.echo(f'ERROR: User {email} already exists.', err=True)
            return

        user = User(email=email, is_admin=True, plan='hobby',
                    subscription_status='inactive')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'✓ Admin user created: {email}')

    @app.cli.command('reset-password')
    @click.argument('email')
    @click.argument('password')
    @with_appcontext
    def reset_password(email, password):
        """Reset the password for any existing user.

        Usage: flask --app run:app reset-password EMAIL PASSWORD
        """
        from app import db
        from app.models import User

        if len(password) < 8:
            click.echo('ERROR: Password must be at least 8 characters.', err=True)
            return

        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f'ERROR: User {email} not found.', err=True)
            return

        user.set_password(password)
        db.session.commit()
        click.echo(f'✓ Password reset for {email}')

    @app.cli.command('make-admin')
    @click.argument('email')
    @with_appcontext
    def make_admin(email):
        """Grant admin privileges to an existing user.

        Usage: flask --app run:app make-admin EMAIL
        """
        from app import db
        from app.models import User

        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f'ERROR: User {email} not found.', err=True)
            return

        user.is_admin = True
        db.session.commit()
        click.echo(f'✓ {email} is now an admin')

    @app.cli.command('list-admins')
    @with_appcontext
    def list_admins():
        """List all admin users."""
        from app.models import User

        admins = User.query.filter_by(is_admin=True).order_by(User.created_at).all()
        if not admins:
            click.echo('No admins found.')
            return

        click.echo(f'{len(admins)} admin user(s):')
        for u in admins:
            click.echo(f'  - {u.email} (id={u.id}, created {u.created_at.strftime("%Y-%m-%d")})')
