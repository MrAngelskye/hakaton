"""Non-destructive case-1 migration. Run inside the caller's transaction.

The same migration upgrades legacy SQLite, legacy PostgreSQL and baseline 001.
Historical times inferred from reports are labelled; they are not new facts.
"""
import re,json

VERSION = '002'

TABLES = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at STAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sites(id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS brigades(id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS equipment(id SERIAL PRIMARY KEY, inventory_number TEXT UNIQUE NOT NULL, name TEXT NOT NULL, site_id INTEGER NOT NULL REFERENCES sites(id), equipment_type TEXT NOT NULL DEFAULT 'legacy', criticality INTEGER NOT NULL DEFAULT 3);
CREATE TABLE IF NOT EXISTS defect_codes(id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'legacy');
CREATE TABLE IF NOT EXISTS materials(id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL, unit TEXT NOT NULL, unit_price REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rpc_results(request_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),method TEXT NOT NULL,result JSONTEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_jobs(report_id INTEGER PRIMARY KEY REFERENCES reports(id),status TEXT NOT NULL,score INTEGER,verdict TEXT,summary TEXT,findings JSONTEXT,criteria JSONTEXT,error TEXT,model TEXT NOT NULL,prompt_version TEXT NOT NULL,created STAMP NOT NULL,finished STAMP,lease_token TEXT,lease_until REAL,queued_at REAL);
CREATE TABLE IF NOT EXISTS report_materials(report_id INTEGER NOT NULL REFERENCES reports(id),line_no INTEGER NOT NULL,material_id INTEGER REFERENCES materials(id),name_snapshot TEXT NOT NULL,quantity REAL NOT NULL,unit TEXT NOT NULL,unit_price REAL NOT NULL,PRIMARY KEY(report_id,line_no));
CREATE TABLE IF NOT EXISTS task_photos(id SERIAL PRIMARY KEY,task_id INTEGER NOT NULL REFERENCES tasks(id),report_id INTEGER REFERENCES reports(id),kind TEXT NOT NULL,object_key TEXT UNIQUE NOT NULL,author_id INTEGER NOT NULL REFERENCES users(id),captured_at STAMP,uploaded_at STAMP NOT NULL,sha256 TEXT,byte_size INTEGER,is_demo BOOL NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS equipment_downtimes(id SERIAL PRIMARY KEY,equipment_id INTEGER NOT NULL REFERENCES equipment(id),task_id INTEGER REFERENCES tasks(id),started_at STAMP NOT NULL,ended_at STAMP,reason TEXT NOT NULL,defect_code_id INTEGER REFERENCES defect_codes(id));
CREATE TABLE IF NOT EXISTS notification_outbox(id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),task_id INTEGER REFERENCES tasks(id),event_key TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,payload JSONTEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at STAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,created_at STAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,sent_at STAMP);
CREATE TABLE IF NOT EXISTS task_assignments(id SERIAL PRIMARY KEY,task_id INTEGER NOT NULL REFERENCES tasks(id),worker_id INTEGER NOT NULL REFERENCES users(id),brigade_id INTEGER REFERENCES brigades(id),assigned_by INTEGER NOT NULL REFERENCES users(id),assigned_at STAMP NOT NULL,ended_at STAMP,reason TEXT NOT NULL DEFAULT '',data_origin TEXT NOT NULL DEFAULT 'recorded');
CREATE TABLE IF NOT EXISTS brigade_memberships(id SERIAL PRIMARY KEY,worker_id INTEGER NOT NULL REFERENCES users(id),brigade_id INTEGER NOT NULL REFERENCES brigades(id),joined_at STAMP NOT NULL,left_at STAMP,data_origin TEXT NOT NULL DEFAULT 'recorded');
CREATE TABLE IF NOT EXISTS task_refusals(id SERIAL PRIMARY KEY,task_id INTEGER NOT NULL REFERENCES tasks(id),worker_id INTEGER NOT NULL REFERENCES users(id),brigade_id INTEGER REFERENCES brigades(id),assignment_version INTEGER NOT NULL,created_at STAMP NOT NULL,reason TEXT NOT NULL,justified INTEGER,assessed_by INTEGER REFERENCES users(id),assessed_at STAMP,assessment_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS work_norms(id SERIAL PRIMARY KEY,equipment_type TEXT NOT NULL,kind TEXT NOT NULL,defect_code_id INTEGER REFERENCES defect_codes(id),hours REAL NOT NULL CHECK(hours>0),complexity REAL NOT NULL DEFAULT 1 CHECK(complexity>0),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS material_norms(norm_id INTEGER NOT NULL REFERENCES work_norms(id),material_id INTEGER NOT NULL REFERENCES materials(id),quantity REAL NOT NULL CHECK(quantity>0),PRIMARY KEY(norm_id,material_id));
CREATE UNIQUE INDEX IF NOT EXISTS current_assignment ON task_assignments(task_id,worker_id) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS current_brigade ON brigade_memberships(worker_id) WHERE left_at IS NULL;
CREATE INDEX IF NOT EXISTS photo_hash ON task_photos(sha256);
CREATE INDEX IF NOT EXISTS active_tasks_due ON tasks(status,deadline);
CREATE INDEX IF NOT EXISTS events_history ON events(task_id,created,id);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_report ON reports(task_id) WHERE status IN ('aiPending','submitted','revision');
CREATE UNIQUE INDEX IF NOT EXISTS one_approved_report ON reports(task_id) WHERE status='approved';
'''

COLUMNS = {
 'users': {'specialty': "TEXT NOT NULL DEFAULT ''", 'grade': 'INTEGER NOT NULL DEFAULT 1', 'brigade_id': 'INTEGER REFERENCES brigades(id)'},
 'tasks': {'site_id': 'INTEGER REFERENCES sites(id)', 'equipment_id': 'INTEGER REFERENCES equipment(id)',
   'brigade_id': 'INTEGER REFERENCES brigades(id)', 'complexity': 'REAL NOT NULL DEFAULT 1', 'norm_id': 'INTEGER REFERENCES work_norms(id)',
   'issued_at':'STAMP', 'accepted_at':'STAMP', 'started_at':'STAMP', 'completed_at':'STAMP', 'closed_at':'STAMP',
   'updated_at':'STAMP', 'rejected_at':'STAMP', 'failure_at':'STAMP', 'queue_position':'INTEGER',
   'refusal_justified':'INTEGER', 'repeat_of_task_id':'INTEGER REFERENCES tasks(id)', 'repeat_confirmed_by':'INTEGER REFERENCES users(id)',
   'rejection_reason':"TEXT NOT NULL DEFAULT ''",
   'data_origin':"TEXT NOT NULL DEFAULT 'recorded'", 'assignment_version':'INTEGER NOT NULL DEFAULT 1'},
 'reports': {'defect_code_id':'INTEGER REFERENCES defect_codes(id)', 'brigade_id':'INTEGER REFERENCES brigades(id)',
   'completed_at':'STAMP', 'photo_issues':"JSONTEXT NOT NULL DEFAULT '[]'", 'data_origin':"TEXT NOT NULL DEFAULT 'recorded'"},
 'events': {'action':"TEXT NOT NULL DEFAULT 'comment'", 'from_status':'TEXT', 'to_status':'TEXT', 'reason':"TEXT NOT NULL DEFAULT ''",
   'actor_kind':"TEXT NOT NULL DEFAULT 'user'", 'data':"JSONTEXT NOT NULL DEFAULT '{}'", 'device_at':'STAMP'},
 'rpc_results': {'payload_hash': "TEXT NOT NULL DEFAULT ''"},
 'ai_jobs': {'confidence':'REAL','quality_1_5':'INTEGER'},
 'task_photos': {'capture_source':"TEXT NOT NULL DEFAULT 'unknown'", 'issues':"JSONTEXT NOT NULL DEFAULT '[]'"},
 'notification_outbox': {'read_at':'STAMP', 'lease_until':'STAMP', 'last_error':"TEXT NOT NULL DEFAULT ''"},
}

class DB:
    def __init__(self, raw, postgres): self.raw=raw; self.postgres=postgres
    def execute(self, sql, args=()):
        return self.raw.execute(sql.replace('?', '%s') if self.postgres else sql, args or None) if self.postgres else self.raw.execute(sql,args)
    def ddl(self, sql):
        types={'SERIAL':'BIGSERIAL' if self.postgres else 'INTEGER', 'STAMP':'TIMESTAMPTZ' if self.postgres else 'TEXT',
               'JSONTEXT':'JSONB' if self.postgres else 'TEXT', 'BOOL':'BOOLEAN' if self.postgres else 'INTEGER'}
        for a,b in types.items():sql=re.sub(r'\b'+a+r'\b',b,sql)
        if self.postgres:
            sql=re.sub(r'\bINTEGER(?= (?:NOT NULL )?REFERENCES)', 'BIGINT',sql)
            sql=sql.replace('unit_price REAL','unit_price NUMERIC(12,2)').replace('quantity REAL','quantity NUMERIC(14,6)')
        return self.execute(sql)
    def columns(self, table):
        if self.postgres:return {r['column_name'] for r in self.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?',('naryadai',table))}
        return {r['name'] for r in self.execute('PRAGMA table_info('+table+')')}

def migrate(raw, postgres=False):
    from app.production_schema import ensure_reference_schema
    db=DB(raw,postgres)
    db.ddl(TABLES.split(';')[0])
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?',(VERSION,)).fetchone():
        ensure_reference_schema(db)
        return False
    if postgres:
        # Old baseline triggers tolerate strings but lose facts. Replaced below.
        for name,table in [('resolve_task_catalogs_trigger','tasks'),('resolve_report_defect_trigger','reports'),('sync_report_details_trigger','reports')]:
            db.execute(f'DROP TRIGGER IF EXISTS {name} ON {table}')
        for table in ('users','tasks','shift_rules','shifts','reports'):
            constraints=db.execute("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid=('naryadai.'||?)::regclass AND contype IN ('c','f')",(table,)).fetchall()
            for r in constraints:
                definition=r['definition'];name=r['conname']
                remove=(table=='users' and 'role' in definition) or (table=='tasks' and any(x in definition for x in ('priority','status','start'))) or table in ('shifts','shift_rules') and 'start' in definition or table=='reports' and 'FOREIGN KEY (task_id, worker_id)' in definition
                if remove:
                    if not re.fullmatch('[a-zA-Z0-9_]+',name):raise ValueError('Invalid constraint name')
                    db.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
        db.execute('ALTER TABLE equipment DROP CONSTRAINT IF EXISTS equipment_name_key') if db.columns('equipment') else None
    for statement in TABLES.split(';')[1:]:
        if statement.strip():db.ddl(statement)
    if postgres:db.execute('ALTER TABLE equipment DROP CONSTRAINT IF EXISTS equipment_name_key')
    for table, columns in COLUMNS.items():
        existing=db.columns(table)
        for name,kind in columns.items():
            if name not in existing:db.ddl(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
    backfill(db)
    # Metadata consistency after historical text imports. Do not invent photo EXIF/hash.
    if postgres:
        from pathlib import Path
        db.execute((Path(__file__).parent/'migration_v2_pg.sql').read_text(encoding='utf-8'))
    db.execute('INSERT INTO schema_migrations(version,description,applied_at) VALUES(?,?,CURRENT_TIMESTAMP)',(VERSION,'Case 1 workflow, units, facts, assignment history and durable notifications'))
    ensure_reference_schema(db)
    return True


def backfill(db):
    # Preserve every historical title. Import old free text into explicitly labelled catalogs.
    for i,r in enumerate(db.execute('SELECT DISTINCT site FROM tasks').fetchall()):
        db.execute('INSERT INTO sites(code,name) VALUES(?,?) ON CONFLICT(name) DO NOTHING',(f'LEGACY-S{i+1}',r['site']))
    for i,r in enumerate(db.execute('SELECT DISTINCT t.equipment,t.site,s.id AS site_id FROM tasks t JOIN sites s ON s.name=t.site').fetchall()):
        if not db.execute('SELECT 1 FROM equipment WHERE name=? AND site_id=?',(r['equipment'],r['site_id'])).fetchone():
            db.execute('INSERT INTO equipment(inventory_number,name,site_id,equipment_type,criticality) VALUES(?,?,?,?,3)',(f'LEGACY-E{i+1}',r['equipment'],r['site_id'],'legacy'))
    db.execute('UPDATE tasks SET site_id=(SELECT id FROM sites WHERE name=tasks.site) WHERE site_id IS NULL')
    db.execute('UPDATE tasks SET equipment_id=(SELECT MIN(id) FROM equipment WHERE name=tasks.equipment AND site_id=tasks.site_id) WHERE equipment_id IS NULL')
    for r in db.execute('SELECT DISTINCT defect FROM reports').fetchall():
        code,_,name=r['defect'].partition(' · ')
        if not db.execute('SELECT 1 FROM defect_codes WHERE code=?',(code,)).fetchone():db.execute('INSERT INTO defect_codes(code,name,category) VALUES(?,?,?)',(code,name or code,'legacy'))
    db.execute("UPDATE reports SET defect_code_id=(SELECT id FROM defect_codes WHERE reports.defect=code OR reports.defect=code||' · '||name) WHERE defect_code_id IS NULL")
    for r in db.execute('SELECT id,materials FROM reports ORDER BY id').fetchall():
        lines=json.loads(r['materials']) if isinstance(r['materials'],str) else r['materials']
        for i,line in enumerate(lines,1):
            m=db.execute('SELECT * FROM materials WHERE name=?',(line['name'],)).fetchone()
            if not m:
                count=db.execute('SELECT count(*) AS n FROM materials').fetchone()['n']
                db.execute('INSERT INTO materials(code,name,unit,unit_price) VALUES(?,?,?,?)',(f'LEGACY-M{count+1}',line['name'],line['unit'],line['price']))
                m=db.execute('SELECT * FROM materials WHERE name=?',(line['name'],)).fetchone()
            # Price is a snapshot per entered unit. Conversion must preserve total cost.
            factors={('г','кг'):.001,('кг','г'):1000,('мл','л'):.001,('л','мл'):1000,('см','м'):.01,('мм','м'):.001}
            factor=1 if line['unit'].rstrip('.')==m['unit'].rstrip('.') else factors.get((line['unit'],m['unit']))
            if factor:
                line.update(quantity=line['quantity']*factor,unit=m['unit'],price=line['price']/factor)
            line['material_id']=m['id']
            db.execute('INSERT INTO report_materials(report_id,line_no,material_id,name_snapshot,quantity,unit,unit_price) VALUES(?,?,?,?,?,?,?) ON CONFLICT(report_id,line_no) DO UPDATE SET material_id=excluded.material_id,quantity=excluded.quantity,unit=excluded.unit,unit_price=excluded.unit_price',(r['id'],i,m['id'],line['name'],line['quantity'],line['unit'],line['price']))
        db.execute('UPDATE reports SET materials=? WHERE id=?',(json.dumps(lines,ensure_ascii=False),r['id']))
    # Legacy PostgreSQL kept these values as TEXT; native baseline uses TIMESTAMPTZ.
    created_stamp='created::TIMESTAMPTZ' if db.postgres else 'created'
    reviewed_stamp='reviewed::TIMESTAMPTZ' if db.postgres else 'reviewed'
    db.execute(f"UPDATE tasks SET issued_at={created_stamp},updated_at={created_stamp},data_origin='legacy_inferred' WHERE issued_at IS NULL")
    db.execute(f"UPDATE reports SET completed_at={created_stamp},brigade_id=(SELECT brigade_id FROM users WHERE id=reports.worker_id),data_origin='legacy_report_time' WHERE completed_at IS NULL")
    for r in db.execute('SELECT id,task_id,worker_id,created,photos FROM reports').fetchall():
        photos=json.loads(r['photos']) if isinstance(r['photos'],str) else r['photos']
        for key in photos:db.execute("INSERT INTO task_photos(task_id,report_id,kind,object_key,author_id,uploaded_at) VALUES(?,?,'after',?,?,?) ON CONFLICT(object_key) DO NOTHING",(r['task_id'],r['id'],key,r['worker_id'],r['created']))
    db.execute(f"UPDATE tasks SET completed_at=(SELECT MIN(completed_at) FROM reports WHERE task_id=tasks.id),closed_at=(SELECT MAX({reviewed_stamp}) FROM reports WHERE task_id=tasks.id AND status='approved') WHERE data_origin='legacy_inferred'")
    db.execute(f"INSERT INTO task_assignments(task_id,worker_id,brigade_id,assigned_by,assigned_at,ended_at,data_origin) SELECT id,worker_id,(SELECT brigade_id FROM users WHERE id=tasks.worker_id),master_id,{created_stamp},CASE WHEN status IN ('approved','cancelled') THEN {created_stamp} ELSE NULL END,'legacy_current_assignment' FROM tasks WHERE worker_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM task_assignments a WHERE a.task_id=tasks.id AND a.worker_id=tasks.worker_id)")
    db.execute("INSERT INTO brigade_memberships(worker_id,brigade_id,joined_at,data_origin) SELECT id,brigade_id,CURRENT_TIMESTAMP,'legacy_current_membership' FROM users WHERE brigade_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM brigade_memberships b WHERE b.worker_id=users.id)")
