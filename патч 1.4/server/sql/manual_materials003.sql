SET LOCAL search_path TO naryadai, public;
CREATE OR REPLACE FUNCTION resolve_report_defect() RETURNS trigger LANGUAGE plpgsql SET search_path=naryadai,pg_temp AS $$
DECLARE m RECORD; item JSONB; normalized JSONB:='[]'; q NUMERIC; unit TEXT; factor NUMERIC; seen TEXT[]:=ARRAY[]::TEXT[];
BEGIN
  IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.worker_id AND role='worker') THEN RAISE EXCEPTION 'Worker role required' USING ERRCODE='23514'; END IF;
  SELECT id INTO NEW.defect_code_id FROM defect_codes WHERE NEW.defect=code OR NEW.defect=code||' · '||name;
  IF NEW.defect_code_id IS NULL THEN RAISE EXCEPTION 'Unknown defect code' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' OR NEW.materials IS DISTINCT FROM OLD.materials THEN
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.materials::jsonb) LOOP
    SELECT * INTO m FROM materials WHERE (item->>'material_id' IS NOT NULL AND id=(item->>'material_id')::BIGINT) OR (item->>'material_id' IS NULL AND name=item->>'name');
    IF m.id IS NULL THEN
      IF item->>'material_id' IS NOT NULL OR COALESCE(item->>'custom','false')<>'true' OR length(trim(item->>'name')) NOT BETWEEN 2 AND 200 OR length(trim(item->>'unit')) NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'Unknown material or invalid manual item' USING ERRCODE='23514';
      END IF;
      q:=(item->>'quantity')::NUMERIC;
      IF q IS NULL OR q<=0 OR q>1000000 OR (item->>'price')::NUMERIC IS NULL OR (item->>'price')::NUMERIC<0 OR (item->>'price')::NUMERIC>100000000 THEN RAISE EXCEPTION 'Invalid manual material quantity or price' USING ERRCODE='23514'; END IF;
      normalized:=normalized||jsonb_build_array(jsonb_build_object('material_id',NULL,'name',trim(item->>'name'),'quantity',q,'unit',trim(item->>'unit'),'price',(item->>'price')::NUMERIC,'custom',true));
      CONTINUE;
    END IF;
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

INSERT INTO schema_migrations(version,description,applied_at) VALUES('003','Manual material snapshots',CURRENT_TIMESTAMP) ON CONFLICT(version) DO NOTHING;
