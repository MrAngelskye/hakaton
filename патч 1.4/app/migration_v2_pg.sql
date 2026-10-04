-- Executed inside migration 002, after additive columns and historical backfill.
SET LOCAL search_path TO naryadai, public;
ALTER TABLE users ADD CONSTRAINT users_role_v2 CHECK(role IN ('worker','master','admin','manager')) NOT VALID;
ALTER TABLE tasks ADD CONSTRAINT tasks_priority_v2 CHECK(priority IN ('urgent','high','normal','scheduled')) NOT VALID;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_v2 CHECK(status IN ('available','planned','accepted','queued','rejected','inProgress','paused','aiPending','submitted','approved','revision','cancelled')) NOT VALID;
ALTER TABLE tasks ADD CONSTRAINT tasks_start_v2 CHECK(start IS NULL OR (start>=0 AND start+duration<=48)) NOT VALID;
ALTER TABLE tasks ADD CONSTRAINT tasks_complexity_v2 CHECK(complexity>0 AND complexity<=10) NOT VALID;
ALTER TABLE shift_rules ADD CONSTRAINT shift_rules_hours_v2 CHECK(start>=0 AND start<24 AND "end">start AND "end"<=start+24) NOT VALID;
ALTER TABLE shifts ADD CONSTRAINT shifts_hours_v2 CHECK((start IS NULL AND "end" IS NULL) OR (start>=0 AND start<24 AND "end">start AND "end"<=start+24)) NOT VALID;
ALTER TABLE task_photos ADD CONSTRAINT photo_time_v2 CHECK(captured_at IS NULL OR captured_at<=uploaded_at+INTERVAL '5 minutes') NOT VALID;
ALTER TABLE users ADD CONSTRAINT users_grade_v2 CHECK(grade BETWEEN 1 AND 6) NOT VALID;
ALTER TABLE materials ADD CONSTRAINT material_price_v2 CHECK(unit_price>=0 AND length(unit)>0) NOT VALID;
ALTER TABLE equipment ADD CONSTRAINT equipment_criticality_v2 CHECK(criticality BETWEEN 1 AND 5) NOT VALID;
ALTER TABLE reports ADD CONSTRAINT report_hours_v2 CHECK(hours>0 AND hours<=24) NOT VALID;
ALTER TABLE reports ADD CONSTRAINT report_score_v2 CHECK(score IS NULL OR score BETWEEN 0 AND 100) NOT VALID;
ALTER TABLE reports ADD CONSTRAINT report_state_v2 CHECK(status IN ('aiPending','submitted','approved','revision','superseded','cancelled')) NOT VALID;
ALTER TABLE reports ADD CONSTRAINT report_acceptance_v2 CHECK(status<>'approved' OR (score IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed IS NOT NULL)) NOT VALID;

CREATE OR REPLACE FUNCTION resolve_task_catalogs() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
DECLARE e RECORD; sid BIGINT; cnt INTEGER; allowed TEXT[];
BEGIN
  IF TG_OP='UPDATE' AND NEW.equipment IS DISTINCT FROM OLD.equipment AND NEW.equipment_id IS NOT DISTINCT FROM OLD.equipment_id THEN NEW.equipment_id:=NULL; END IF;
  IF TG_OP='UPDATE' AND NEW.site IS DISTINCT FROM OLD.site AND NEW.site_id IS NOT DISTINCT FROM OLD.site_id THEN NEW.site_id:=NULL; END IF;
  IF NEW.site_id IS NULL THEN SELECT id INTO NEW.site_id FROM sites WHERE name=NEW.site; END IF;
  IF NEW.equipment_id IS NULL THEN
    SELECT count(*),min(id) INTO cnt,NEW.equipment_id FROM equipment WHERE name=NEW.equipment AND site_id=NEW.site_id;
    IF cnt<>1 THEN RAISE EXCEPTION 'Select equipment by catalog ID' USING ERRCODE='23514'; END IF;
  END IF;
  SELECT * INTO e FROM equipment WHERE id=NEW.equipment_id;
  IF e.id IS NULL OR NEW.site_id IS NULL OR e.site_id<>NEW.site_id THEN RAISE EXCEPTION 'Equipment/site mismatch' USING ERRCODE='23514'; END IF;
  SELECT name INTO NEW.site FROM sites WHERE id=NEW.site_id; NEW.equipment:=e.name;
  IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.master_id AND role IN ('master','admin')) OR
     (NEW.worker_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.worker_id AND role='worker')) THEN
    RAISE EXCEPTION 'Invalid issuer or worker role' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status THEN
    allowed:=CASE OLD.status
      WHEN 'available' THEN ARRAY['planned','accepted','queued','cancelled']
      WHEN 'planned' THEN ARRAY['accepted','queued','rejected','inProgress','available','cancelled']
      WHEN 'accepted' THEN ARRAY['queued','inProgress','rejected','planned','cancelled']
      WHEN 'queued' THEN ARRAY['accepted','inProgress','rejected','planned','cancelled']
      WHEN 'rejected' THEN ARRAY['planned','available','cancelled']
      WHEN 'inProgress' THEN ARRAY['paused','submitted','aiPending','planned','cancelled']
      WHEN 'paused' THEN ARRAY['inProgress','planned','cancelled']
      WHEN 'revision' THEN ARRAY['submitted','aiPending','inProgress','planned','cancelled']
      WHEN 'aiPending' THEN ARRAY['submitted','revision']
      WHEN 'submitted' THEN ARRAY['approved','revision'] ELSE ARRAY[]::TEXT[] END;
    IF NOT NEW.status=ANY(allowed) THEN RAISE EXCEPTION 'Illegal task transition' USING ERRCODE='23514'; END IF;
    IF NEW.status IN ('accepted','queued','inProgress') THEN NEW.accepted_at:=COALESCE(NEW.accepted_at,CURRENT_TIMESTAMP); END IF;
    IF NEW.status='inProgress' THEN NEW.started_at:=COALESCE(NEW.started_at,CURRENT_TIMESTAMP); END IF;
    IF NEW.status='rejected' AND length(NEW.rejection_reason)<3 THEN RAISE EXCEPTION 'Rejection reason required' USING ERRCODE='23514'; END IF;
    IF NEW.status='rejected' THEN NEW.rejected_at:=COALESCE(NEW.rejected_at,CURRENT_TIMESTAMP); END IF;
    IF NEW.status='paused' AND NOT EXISTS(SELECT 1 FROM pauses WHERE task_id=NEW.id AND ended IS NULL AND length(reason)>=3) THEN RAISE EXCEPTION 'Pause reason required' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='UPDATE' AND OLD.status IN ('approved','cancelled') AND (NEW.worker_id,NEW.equipment_id,NEW.brigade_id,NEW.completed_at) IS DISTINCT FROM (OLD.worker_id,OLD.equipment_id,OLD.brigade_id,OLD.completed_at) THEN RAISE EXCEPTION 'Closed task history is immutable' USING ERRCODE='23514'; END IF;
  IF NEW.status='approved' AND (TG_OP='INSERT' OR OLD.status<>'approved') THEN
    IF NOT EXISTS(SELECT 1 FROM reports WHERE task_id=NEW.id AND status='approved') THEN RAISE EXCEPTION 'Approved report required' USING ERRCODE='23514'; END IF;
  END IF;
  NEW.updated_at:=CURRENT_TIMESTAMP;
  RETURN NEW;
END $$;
CREATE TRIGGER resolve_task_catalogs_trigger BEFORE INSERT OR UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION resolve_task_catalogs();

CREATE OR REPLACE FUNCTION resolve_report_defect() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
DECLARE m RECORD; item JSONB; normalized JSONB:='[]'; q NUMERIC; unit TEXT; factor NUMERIC; seen TEXT[]:=ARRAY[]::TEXT[];
BEGIN
  IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.worker_id AND role='worker') THEN RAISE EXCEPTION 'Worker role required' USING ERRCODE='23514'; END IF;
  SELECT id INTO NEW.defect_code_id FROM defect_codes WHERE NEW.defect=code OR NEW.defect=code||' · '||name;
  IF NEW.defect_code_id IS NULL THEN RAISE EXCEPTION 'Unknown defect code' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' OR NEW.materials IS DISTINCT FROM OLD.materials THEN
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.materials::jsonb) LOOP
    SELECT * INTO m FROM materials WHERE (item->>'material_id' IS NOT NULL AND id=(item->>'material_id')::BIGINT) OR (item->>'material_id' IS NULL AND name=item->>'name');
    IF m.id IS NULL THEN RAISE EXCEPTION 'Unknown material' USING ERRCODE='23514'; END IF;
    unit:=item->>'unit'; factor:=CASE WHEN unit=m.unit OR replace(unit,'.','')=replace(m.unit,'.','') THEN 1
      WHEN unit='г' AND m.unit='кг' THEN 0.001 WHEN unit='кг' AND m.unit='г' THEN 1000
      WHEN unit='мл' AND m.unit='л' THEN 0.001 WHEN unit='л' AND m.unit='мл' THEN 1000
      WHEN unit='см' AND m.unit='м' THEN 0.01 WHEN unit='мм' AND m.unit='м' THEN 0.001 ELSE NULL END;
    IF factor IS NULL THEN RAISE EXCEPTION 'Incompatible material unit' USING ERRCODE='23514'; END IF;
    q:=(item->>'quantity')::NUMERIC*factor;
    IF q<=0 OR q>1000000 THEN RAISE EXCEPTION 'Invalid material quantity' USING ERRCODE='23514'; END IF;
    normalized:=normalized||jsonb_build_array(jsonb_build_object('material_id',m.id,'name',m.name,'quantity',q,'unit',m.unit,'price',m.unit_price));
  END LOOP;
  NEW.materials:=normalized;
  END IF;
  IF jsonb_typeof(NEW.photos::jsonb)<>'array' OR jsonb_array_length(NEW.photos::jsonb)>5 THEN RAISE EXCEPTION 'Invalid photos' USING ERRCODE='23514'; END IF;
  IF NEW.status='approved' THEN
    IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.reviewer_id AND role IN ('master','admin')) THEN RAISE EXCEPTION 'Reviewer role required' USING ERRCODE='23514'; END IF;
    IF EXISTS(SELECT 1 FROM tasks WHERE id=NEW.task_id AND kind='Внеплановая') AND jsonb_array_length(NEW.photos::jsonb)=0 THEN RAISE EXCEPTION 'After photo required for closure' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER resolve_report_defect_trigger BEFORE INSERT OR UPDATE ON reports FOR EACH ROW EXECUTE FUNCTION resolve_report_defect();

CREATE OR REPLACE FUNCTION sync_report_details() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
DECLARE item JSONB; n INTEGER:=0; photo_name TEXT;
BEGIN
  DELETE FROM report_materials WHERE report_id=NEW.id;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.materials::jsonb) LOOP
    n:=n+1;
    INSERT INTO report_materials(report_id,line_no,material_id,name_snapshot,quantity,unit,unit_price)
      VALUES(NEW.id,n,(item->>'material_id')::BIGINT,item->>'name',(item->>'quantity')::NUMERIC,item->>'unit',(item->>'price')::NUMERIC);
  END LOOP;
  DELETE FROM task_photos WHERE report_id=NEW.id AND NOT object_key IN (SELECT jsonb_array_elements_text(NEW.photos::jsonb));
  FOR photo_name IN SELECT jsonb_array_elements_text(NEW.photos::jsonb) LOOP
    IF photo_name<>regexp_replace(photo_name,'^.*/','') OR photo_name LIKE '%\\%' THEN RAISE EXCEPTION 'Invalid photo key' USING ERRCODE='23514'; END IF;
    INSERT INTO task_photos(task_id,report_id,kind,object_key,author_id,uploaded_at)
      VALUES(NEW.task_id,NEW.id,'after',photo_name,NEW.worker_id,NEW.created::TIMESTAMPTZ) ON CONFLICT(object_key) DO NOTHING;
    IF NOT EXISTS(SELECT 1 FROM task_photos WHERE object_key=photo_name AND report_id=NEW.id) THEN RAISE EXCEPTION 'Photo belongs to another report' USING ERRCODE='23514'; END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER sync_report_details_trigger AFTER INSERT OR UPDATE OF materials,photos ON reports FOR EACH ROW EXECUTE FUNCTION sync_report_details();

CREATE OR REPLACE FUNCTION audit_task_change() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
BEGIN
  IF (OLD.status,OLD.priority,OLD.worker_id,OLD.brigade_id) IS DISTINCT FROM (NEW.status,NEW.priority,NEW.worker_id,NEW.brigade_id) AND COALESCE(current_setting('naryadai.service_write',true),'')<>'1' THEN
    INSERT INTO events(task_id,actor_id,message,created,action,from_status,to_status,actor_kind,data)
      VALUES(NEW.id,NEW.master_id,'Direct database change',CURRENT_TIMESTAMP,'db_change',OLD.status,NEW.status,'integration',jsonb_build_object('old_priority',OLD.priority,'priority',NEW.priority,'old_worker_id',OLD.worker_id,'worker_id',NEW.worker_id));
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS task_audit_v2 ON tasks;
CREATE TRIGGER task_audit_v2 AFTER UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION audit_task_change();

CREATE OR REPLACE FUNCTION guard_downtime() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
BEGIN
  IF NEW.task_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM tasks WHERE id=NEW.task_id AND equipment_id=NEW.equipment_id) THEN RAISE EXCEPTION 'Downtime equipment/task mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.ended_at IS NOT NULL AND NEW.ended_at<NEW.started_at THEN RAISE EXCEPTION 'Invalid downtime interval' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER downtime_guard_v2 BEFORE INSERT OR UPDATE ON equipment_downtimes FOR EACH ROW EXECUTE FUNCTION guard_downtime();

-- Historical mixed units are converted where known, never labelled as kilograms otherwise.
UPDATE report_materials rm SET quantity=rm.quantity*0.001,unit_price=rm.unit_price*1000,unit='кг' FROM materials m WHERE rm.material_id=m.id AND rm.unit='г' AND m.unit='кг';
UPDATE report_materials rm SET quantity=rm.quantity*0.001,unit_price=rm.unit_price*1000,unit='л' FROM materials m WHERE rm.material_id=m.id AND rm.unit='мл' AND m.unit='л';
DROP VIEW IF EXISTS material_usage;
CREATE VIEW material_usage WITH(security_invoker=true) AS
 SELECT m.id,m.code,m.name,rm.unit,sum(rm.quantity) AS quantity,sum(rm.quantity*rm.unit_price) AS cost
 FROM report_materials rm JOIN reports r ON r.id=rm.report_id JOIN materials m ON m.id=rm.material_id
 WHERE r.status='approved' GROUP BY m.id,rm.unit;
CREATE OR REPLACE VIEW equipment_failures WITH(security_invoker=true) AS
 SELECT e.id,e.inventory_number,e.name,s.name AS site,
 count(t.id) FILTER(WHERE t.kind='Внеплановая' AND t.status='approved') AS unplanned_repairs,
 count(t.id) FILTER(WHERE t.status='approved') AS closed_tasks
 FROM equipment e JOIN sites s ON s.id=e.site_id LEFT JOIN tasks t ON t.equipment_id=e.id
 GROUP BY e.id,e.inventory_number,e.name,s.name;
CREATE OR REPLACE VIEW employee_metrics WITH(security_invoker=true) AS
 SELECT u.id,u.username,u.name,u.brigade_id,
 count(r.id) FILTER(WHERE r.status='approved') AS closed_tasks,
 round(avg(r.score) FILTER(WHERE r.status='approved'),2) AS quality_score,
 count(r.id) FILTER(WHERE r.status='approved' AND r.completed_at<=t.deadline::TIMESTAMPTZ) AS on_time_tasks,
 count(r.id) FILTER(WHERE r.status='superseded') AS revision_reports
 FROM users u LEFT JOIN reports r ON r.worker_id=u.id LEFT JOIN tasks t ON t.id=r.task_id
 WHERE u.role='worker' GROUP BY u.id;
REVOKE ALL ON ALL TABLES IN SCHEMA naryadai FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA naryadai FROM PUBLIC;
DO $$ DECLARE t RECORD; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='naryadai' LOOP
   EXECUTE format('ALTER TABLE naryadai.%I ENABLE ROW LEVEL SECURITY',t.tablename);
 END LOOP;
END $$;
