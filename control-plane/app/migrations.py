from sqlalchemy import text


MIGRATIONS = [
    # ---- User: admin/billing ----
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS plan VARCHAR(50) NOT NULL DEFAULT \'hobby\'',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) NOT NULL DEFAULT \'inactive\'',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_user_stripe_customer ON "user" (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL',

    # ---- User: profile ----
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS name VARCHAR(100)',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS phone VARCHAR(30)',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS country VARCHAR(2)',
    'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS signup_ip VARCHAR(45)',

    # ---- Project: instance plan ----
    'ALTER TABLE project ADD COLUMN IF NOT EXISTS instance_plan VARCHAR(50) NOT NULL DEFAULT \'starter\'',

    # ---- Payment: transaction ledger ----
    '''CREATE TABLE IF NOT EXISTS payment (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        plan_tier VARCHAR(50) NOT NULL,
        amount_usd NUMERIC(10, 2) NOT NULL,
        amount_local NUMERIC(10, 2),
        currency VARCHAR(10) DEFAULT 'USD',
        provider VARCHAR(20) NOT NULL,
        provider_ref VARCHAR(255),
        status VARCHAR(50) DEFAULT 'pending',
        raw_response TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        finished_at TIMESTAMP
    )''',
    'CREATE INDEX IF NOT EXISTS idx_payment_user ON payment (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_payment_ref ON payment (provider_ref)',
    'CREATE INDEX IF NOT EXISTS idx_payment_status ON payment (status)',
]


def run_migrations(db):
    applied = 0
    for sql in MIGRATIONS:
        try:
            db.session.execute(text(sql))
            db.session.commit()
            applied += 1
        except Exception as e:
            db.session.rollback()
            print(f"[migrations] skipped: {sql[:80]}... ({e})")
    print(f"[migrations] ran {applied}/{len(MIGRATIONS)} statements OK")
