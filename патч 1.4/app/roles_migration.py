"""Retire an obsolete role while preserving historical foreign keys."""


def ensure_supported_roles(db):
    if db.execute("SELECT 1 FROM schema_migrations WHERE version='005'").fetchone():
        return
    db.execute("UPDATE users SET active=0 WHERE role='manager'")
    if db.columns('sessions'):
        db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role='manager')")
    if db.postgres:
        db.execute('ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_v2')
        db.execute("ALTER TABLE users ADD CONSTRAINT users_role_v5 CHECK(role IN ('worker','master','admin') OR (role='manager' AND active=0))")
    else:
        for action in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS users_supported_role_{action.lower()}
                BEFORE {action} ON users
                WHEN NEW.active=1 AND NEW.role NOT IN ('worker','master','admin')
                BEGIN SELECT RAISE(ABORT,'Unsupported active role'); END''')
    db.execute("INSERT INTO schema_migrations(version,description,applied_at) VALUES('005','Retire manager role and revoke legacy sessions',CURRENT_TIMESTAMP)")
