"""Add provenance and reference data without inventing production records.

Migration 004 is additive, shared by SQLite and PostgreSQL. Text identifiers avoid
confusing reference photographs/templates with operational task/photo IDs.
"""

VERSION = '004'
TABLES = '''
CREATE TABLE IF NOT EXISTS reference_sources(
 source_id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
 publisher TEXT NOT NULL, source_kind TEXT NOT NULL, retrieved_at TEXT NOT NULL,
 published_at TEXT, license_id TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reference_provenance(
 entity_type TEXT NOT NULL, entity_key TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 status TEXT NOT NULL CHECK(status IN ('public_verified','industry_reference','editorial_template','anonymized_profile')),
 company_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(company_confirmed IN (0,1)),
 note TEXT NOT NULL, PRIMARY KEY(entity_type,entity_key,source_id));
CREATE TABLE IF NOT EXISTS material_reference_metadata(
 material_id INTEGER PRIMARY KEY REFERENCES materials(id),
 source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 manufacturer TEXT NOT NULL, model TEXT NOT NULL,
 price_known INTEGER NOT NULL DEFAULT 0 CHECK(price_known IN (0,1)),
 company_usage_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(company_usage_confirmed IN (0,1)),
 note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_provenance(
 user_id INTEGER PRIMARY KEY REFERENCES users(id),
 source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 identity_status TEXT NOT NULL CHECK(identity_status IN ('unassigned_anonymized_profile','user_entered')),
 grade_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(grade_confirmed IN (0,1)),
 note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equipment_reference_types(
 code TEXT PRIMARY KEY, name TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 company_context INTEGER NOT NULL DEFAULT 0 CHECK(company_context IN (0,1)), note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS work_order_templates(
 template_id TEXT PRIMARY KEY, title TEXT NOT NULL, equipment_category TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('Плановая','Внеплановая')),
 problem_description TEXT NOT NULL, closeout_requirements TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved')),
 approved_by INTEGER REFERENCES users(id), approved_at TEXT,
 CHECK((status='draft' AND approved_by IS NULL AND approved_at IS NULL) OR
       (status='approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)));
CREATE TABLE IF NOT EXISTS training_photos(
 photo_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES reference_sources(source_id),
 original_url TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
 sha256 TEXT NOT NULL UNIQUE, equipment_category TEXT NOT NULL,
 source_reported_condition TEXT NOT NULL, observation TEXT NOT NULL,
 license_id TEXT NOT NULL, attribution TEXT NOT NULL, split_group TEXT NOT NULL,
 company_image INTEGER NOT NULL DEFAULT 0 CHECK(company_image IN (0,1)),
 annotation_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK(annotation_status IN ('unreviewed','expert_reviewed','rejected')),
 training_approved INTEGER NOT NULL DEFAULT 0 CHECK(training_approved IN (0,1)),
 paired_photo_id TEXT REFERENCES training_photos(photo_id),
 CHECK(training_approved=0 OR annotation_status='expert_reviewed'),
 CHECK(paired_photo_id IS NULL OR paired_photo_id<>photo_id));
CREATE INDEX IF NOT EXISTS training_photos_group ON training_photos(split_group);
'''

TABLE_NAMES = (
    'reference_sources', 'reference_provenance', 'material_reference_metadata',
    'account_provenance', 'equipment_reference_types', 'work_order_templates', 'training_photos',
)

BUSINESS_TABLES = (
    'users','tasks','reports','events','pauses','sites','equipment','materials','defect_codes','brigades',
    'work_norms','material_norms','shift_rules','shifts','task_photos','report_materials','task_assignments',
    'brigade_memberships','equipment_downtimes','task_refusals','ai_jobs','notification_outbox',
) + TABLE_NAMES


def ensure_reference_schema(db):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (VERSION,)).fetchone():
        return
    for statement in TABLES.split(';'):
        if statement.strip():
            db.ddl(statement)
    if db.postgres:
        for table in TABLE_NAMES:
            db.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            db.execute(f'REVOKE ALL ON TABLE {table} FROM PUBLIC')
    db.execute('INSERT INTO schema_migrations(version,description,applied_at) VALUES(?,?,CURRENT_TIMESTAMP)',
               (VERSION, 'Public-source references, anonymized accounts, work templates and training-photo provenance'))
