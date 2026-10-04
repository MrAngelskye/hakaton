-- PostgreSQL baseline for a NEW dedicated naryadai schema.
-- App contract: MrAngelskye/hakaton, cloud-1.4, commit 836961552f2389042687ffd1df4b7f512387cc0e.
BEGIN;
CREATE SCHEMA IF NOT EXISTS naryadai;
SET LOCAL search_path TO naryadai, public;
SET LOCAL TIME ZONE 'Asia/Qyzylorda';

DO $$
BEGIN
  IF to_regclass('naryadai.users') IS NOT NULL
     AND to_regclass('naryadai.schema_migrations') IS NULL THEN
    RAISE EXCEPTION 'Existing unversioned naryadai schema: use a separate empty test database. No data was changed.';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_metadata (key TEXT PRIMARY KEY, value JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS sites (
  id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS brigades (
  id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS equipment (
  id BIGSERIAL PRIMARY KEY, inventory_number TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL,
  site_id BIGINT NOT NULL REFERENCES sites(id), equipment_type TEXT NOT NULL,
  criticality INTEGER NOT NULL CHECK (criticality BETWEEN 1 AND 5),
  UNIQUE(id, site_id)
);
CREATE TABLE IF NOT EXISTS defect_codes (
  id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
  UNIQUE(code, name)
);
CREATE TABLE IF NOT EXISTS materials (
  id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL,
  unit TEXT NOT NULL CHECK (length(unit)>0), unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price>=0)
);
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, job TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('worker','master','admin','manager')),
  salt TEXT NOT NULL, password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  specialty TEXT NOT NULL DEFAULT '', grade INTEGER NOT NULL DEFAULT 1 CHECK (grade BETWEEN 1 AND 6),
  brigade_id BIGINT REFERENCES brigades(id)
);
CREATE TABLE IF NOT EXISTS tasks (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
  site TEXT NOT NULL, equipment TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('urgent','normal')),
  kind TEXT NOT NULL CHECK (kind IN ('Плановая','Внеплановая')),
  duration DOUBLE PRECISION NOT NULL CHECK (duration>=0.5 AND duration<=10),
  day DATE NOT NULL, start DOUBLE PRECISION CHECK (start>=0 AND start<24),
  deadline TIMESTAMPTZ NOT NULL, worker_id BIGINT REFERENCES users(id),
  master_id BIGINT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('available','planned','inProgress','paused','aiPending','submitted','approved','revision','cancelled')),
  created TIMESTAMPTZ NOT NULL,
  site_id BIGINT REFERENCES sites(id), equipment_id BIGINT,
  UNIQUE(id,worker_id),
  FOREIGN KEY (equipment_id,site_id) REFERENCES equipment(id,site_id),
  CHECK (start IS NULL OR start+duration<=24)
);
CREATE TABLE IF NOT EXISTS reports (
  id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id),
  worker_id BIGINT NOT NULL REFERENCES users(id), work TEXT NOT NULL,
  result TEXT NOT NULL, defect TEXT NOT NULL, hours DOUBLE PRECISION NOT NULL CHECK (hours>0 AND hours<=24),
  materials JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(materials)='array'),
  photos JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(photos)='array'),
  status TEXT NOT NULL CHECK (status IN ('aiPending','submitted','approved','revision','superseded','cancelled')),
  score INTEGER CHECK (score BETWEEN 0 AND 100), comment TEXT NOT NULL DEFAULT '',
  reviewer_id BIGINT REFERENCES users(id), created TIMESTAMPTZ NOT NULL, reviewed TIMESTAMPTZ,
  defect_code_id BIGINT REFERENCES defect_codes(id),
  UNIQUE(id,task_id),
  FOREIGN KEY(task_id,worker_id) REFERENCES tasks(id,worker_id),
  CHECK (status<>'approved' OR (score IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed IS NOT NULL)),
  CHECK (reviewed IS NULL OR reviewed>=created)
);
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id),
  actor_id BIGINT NOT NULL REFERENCES users(id), message TEXT NOT NULL, created TIMESTAMPTZ NOT NULL,
  action TEXT NOT NULL DEFAULT 'comment', from_status TEXT, to_status TEXT, reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shift_rules (
  worker_id BIGINT NOT NULL REFERENCES users(id), weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
  start DOUBLE PRECISION NOT NULL, "end" DOUBLE PRECISION NOT NULL,
  PRIMARY KEY(worker_id,weekday), CHECK (start>=0 AND start<"end" AND "end"<24)
);
CREATE TABLE IF NOT EXISTS shifts (
  worker_id BIGINT NOT NULL REFERENCES users(id), day DATE NOT NULL,
  start DOUBLE PRECISION, "end" DOUBLE PRECISION, updated_by BIGINT REFERENCES users(id), updated TIMESTAMPTZ,
  PRIMARY KEY(worker_id,day),
  CHECK ((start IS NULL AND "end" IS NULL) OR (start IS NOT NULL AND "end" IS NOT NULL AND start>=0 AND start<"end" AND "end"<24))
);
CREATE TABLE IF NOT EXISTS pauses (
  id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id),
  actor_id BIGINT NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
  started TIMESTAMPTZ NOT NULL, ended TIMESTAMPTZ, ended_by BIGINT REFERENCES users(id),
  CHECK (ended IS NULL OR ended>=started)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_pause ON pauses(task_id) WHERE ended IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_current_report ON reports(task_id) WHERE status IN ('aiPending','submitted','revision');
CREATE UNIQUE INDEX IF NOT EXISTS one_approved_report ON reports(task_id) WHERE status='approved';
CREATE INDEX IF NOT EXISTS report_task ON reports(task_id);
CREATE INDEX IF NOT EXISTS task_worker_day ON tasks(worker_id,day,start);
CREATE INDEX IF NOT EXISTS task_status_deadline ON tasks(status,deadline);
CREATE INDEX IF NOT EXISTS task_equipment_day ON tasks(equipment_id,day);
CREATE INDEX IF NOT EXISTS event_task_time ON events(task_id,created,id);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), expires DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS rpc_results (
  request_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), method TEXT NOT NULL,
  result JSONB NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_jobs (
  report_id BIGINT PRIMARY KEY REFERENCES reports(id),
  status TEXT NOT NULL CHECK (status IN ('queued','processing','completed','failed','skipped')),
  score INTEGER CHECK (score BETWEEN 0 AND 100), verdict TEXT, summary TEXT, findings JSONB, criteria JSONB,
  error TEXT, model TEXT NOT NULL, prompt_version TEXT NOT NULL, created TIMESTAMPTZ NOT NULL,
  finished TIMESTAMPTZ, lease_token TEXT, lease_until DOUBLE PRECISION, queued_at DOUBLE PRECISION,
  CHECK (finished IS NULL OR finished>=created)
);
CREATE INDEX IF NOT EXISTS ai_queue ON ai_jobs(status,report_id);
CREATE TABLE IF NOT EXISTS ai_worker_state (id BIGINT PRIMARY KEY, last_seen DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS chat_conversations (
  id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_requests (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES chat_conversations(id),
  message TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('queued','processing','completed','failed')),
  model TEXT NOT NULL DEFAULT '', created DOUBLE PRECISION NOT NULL, finished DOUBLE PRECISION,
  lease_token TEXT, lease_until DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS chat_owner ON chat_conversations(user_id,created);
CREATE INDEX IF NOT EXISTS chat_queue ON chat_requests(status,created);
CREATE INDEX IF NOT EXISTS chat_history ON chat_requests(conversation_id,created);

CREATE TABLE IF NOT EXISTS report_materials (
  report_id BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL CHECK (line_no>0), material_id BIGINT REFERENCES materials(id),
  name_snapshot TEXT NOT NULL, quantity NUMERIC(14,3) NOT NULL CHECK (quantity>0),
  unit TEXT NOT NULL, unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price>=0),
  PRIMARY KEY(report_id,line_no)
);
CREATE TABLE IF NOT EXISTS task_photos (
  id BIGSERIAL PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id), report_id BIGINT REFERENCES reports(id),
  kind TEXT NOT NULL CHECK (kind IN ('before','after')), object_key TEXT UNIQUE NOT NULL,
  author_id BIGINT NOT NULL REFERENCES users(id), captured_at TIMESTAMPTZ, uploaded_at TIMESTAMPTZ NOT NULL,
  sha256 TEXT CHECK (sha256 IS NULL OR sha256~'^[a-f0-9]{64}$'), byte_size BIGINT CHECK (byte_size>0),
  is_demo BOOLEAN NOT NULL DEFAULT false,
  FOREIGN KEY(report_id,task_id) REFERENCES reports(id,task_id),
  CHECK ((kind='before' AND report_id IS NULL) OR (kind='after' AND report_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS photo_task ON task_photos(task_id,kind);
CREATE TABLE IF NOT EXISTS equipment_downtimes (
  id BIGSERIAL PRIMARY KEY, equipment_id BIGINT NOT NULL REFERENCES equipment(id),
  task_id BIGINT REFERENCES tasks(id), started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ,
  reason TEXT NOT NULL, defect_code_id BIGINT REFERENCES defect_codes(id),
  CHECK (ended_at IS NULL OR ended_at>=started_at)
);
CREATE INDEX IF NOT EXISTS downtime_equipment ON equipment_downtimes(equipment_id,started_at);
CREATE TABLE IF NOT EXISTS notification_outbox (
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), task_id BIGINT REFERENCES tasks(id),
  event_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sending','sent','failed')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0), next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS notification_ready ON notification_outbox(status,next_attempt_at);

-- Keep legacy string fields usable while filling catalog IDs for known entries.
CREATE OR REPLACE FUNCTION resolve_task_catalogs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sid BIGINT; eid BIGINT; esid BIGINT;
BEGIN
  SELECT id INTO sid FROM sites WHERE name=NEW.site;
  SELECT id,site_id INTO eid,esid FROM equipment WHERE name=NEW.equipment;
  IF eid IS NOT NULL AND sid IS DISTINCT FROM esid THEN
    RAISE EXCEPTION 'Equipment belongs to a different site' USING ERRCODE='23514';
  END IF;
  NEW.site_id:=sid; NEW.equipment_id:=eid;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS resolve_task_catalogs_trigger ON tasks;
CREATE TRIGGER resolve_task_catalogs_trigger BEFORE INSERT OR UPDATE OF site,equipment ON tasks
  FOR EACH ROW EXECUTE FUNCTION resolve_task_catalogs();

CREATE OR REPLACE FUNCTION resolve_report_defect() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  SELECT id INTO NEW.defect_code_id FROM defect_codes
    WHERE NEW.defect=code OR NEW.defect=code||' · '||name;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS resolve_report_defect_trigger ON reports;
CREATE TRIGGER resolve_report_defect_trigger BEFORE INSERT OR UPDATE OF defect ON reports
  FOR EACH ROW EXECUTE FUNCTION resolve_report_defect();

CREATE OR REPLACE FUNCTION sync_report_details() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item JSONB; n INTEGER:=0; photo_name TEXT;
BEGIN
  DELETE FROM report_materials WHERE report_id=NEW.id;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.materials) LOOP
    n:=n+1;
    INSERT INTO report_materials(report_id,line_no,material_id,name_snapshot,quantity,unit,unit_price)
      VALUES(NEW.id,n,(SELECT id FROM materials WHERE name=item->>'name'),item->>'name',
        (item->>'quantity')::NUMERIC,item->>'unit',COALESCE((item->>'price')::NUMERIC,0));
  END LOOP;
  FOR photo_name IN SELECT jsonb_array_elements_text(NEW.photos) LOOP
    INSERT INTO task_photos(task_id,report_id,kind,object_key,author_id,uploaded_at)
      VALUES(NEW.task_id,NEW.id,'after',photo_name,NEW.worker_id,NEW.created)
      ON CONFLICT(object_key) DO NOTHING;
  END LOOP;
  IF EXISTS(SELECT 1 FROM task_photos WHERE object_key IN (SELECT jsonb_array_elements_text(NEW.photos))
            AND report_id IS DISTINCT FROM NEW.id) THEN
    RAISE EXCEPTION 'Photo already belongs to a different report' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS sync_report_details_trigger ON reports;
CREATE TRIGGER sync_report_details_trigger AFTER INSERT OR UPDATE OF materials,photos ON reports
  FOR EACH ROW EXECUTE FUNCTION sync_report_details();

CREATE OR REPLACE VIEW equipment_failures AS
  SELECT e.id,e.inventory_number,e.name,s.name AS site,
    count(t.id) FILTER (WHERE t.kind='Внеплановая' AND t.status='approved') AS unplanned_repairs,
    count(t.id) FILTER (WHERE t.status='approved') AS closed_tasks
  FROM equipment e JOIN sites s ON s.id=e.site_id LEFT JOIN tasks t ON t.equipment_id=e.id
  GROUP BY e.id,e.inventory_number,e.name,s.name;
CREATE OR REPLACE VIEW employee_metrics AS
  SELECT u.id,u.username,u.name,u.brigade_id,
    count(r.id) FILTER (WHERE r.status='approved') AS closed_tasks,
    round(avg(r.score) FILTER (WHERE r.status='approved'),2) AS quality_score,
    count(r.id) FILTER (WHERE r.status='approved' AND r.created<=t.deadline) AS on_time_tasks,
    count(r.id) FILTER (WHERE r.status='superseded') AS revision_reports
  FROM users u LEFT JOIN reports r ON r.worker_id=u.id LEFT JOIN tasks t ON t.id=r.task_id
  WHERE u.role='worker' GROUP BY u.id;
CREATE OR REPLACE VIEW material_usage AS
  SELECT m.id,m.code,m.name,m.unit,sum(rm.quantity) AS quantity,
    sum(rm.quantity*rm.unit_price) AS cost
  FROM report_materials rm JOIN reports r ON r.id=rm.report_id JOIN materials m ON m.id=rm.material_id
  WHERE r.status='approved' GROUP BY m.id;

REVOKE ALL ON SCHEMA naryadai FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA naryadai FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA naryadai FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA naryadai REVOKE ALL ON TABLES FROM PUBLIC;
DO $$
DECLARE t RECORD;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='naryadai' LOOP
    EXECUTE format('ALTER TABLE naryadai.%I ENABLE ROW LEVEL SECURITY',t.tablename);
  END LOOP;
END $$;
INSERT INTO schema_migrations(version,description)
  VALUES('001','Native PostgreSQL schema compatible with cloud-1.4') ON CONFLICT(version) DO NOTHING;
COMMIT;
