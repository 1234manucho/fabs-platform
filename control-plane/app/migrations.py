"""
Idempotent schema migrations that run on every app startup.

PostgreSQL's ADD COLUMN IF NOT EXISTS makes every statement safe to re-run,
so this can run on every boot without harm. New migrations are simply
appended to the list at the bottom.
"""
from sqlalchemy import text


MIGRATIONS = [
    # ---- User table: admin/billing columns ----
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS plan VARCHAR(50) NOT NULL DEFAULT \'hobby\'',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) NOT NULL DEFAULT \'inactive\'',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_user_stripe_customer ON "user" (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL',

    # ---- Project table: instance plan ----
    'ALTER TABLE project ADD COLUMN IF NOT EXISTS instance_plan VARCHAR(50) NOT NULL DEFAULT \'starter\'',
]


def run_migrations(db):
    """Execute all migrations. Safe to call on every startup."""
    applied = 0
    for sql in MIGRATIONS:
        try:
            db.session.execute(text(sql))
            db.session.commit()
            applied += 1
        except Exception as e:
            db.session.rollback()
            # Log but don't crash — most failures are benign "already exists"
            print(f"[migrations] skipped: {sql[:60]}... ({e})")
    print(f"[migrations] ran {applied}/{len(MIGRATIONS)} statements OK")
