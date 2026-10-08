-- SYNTHETIC TRAINING DATA ONLY. Not a production database.
-- All people, inventory units, work orders and decisions are fictional.
CREATE SCHEMA IF NOT EXISTS naryadai_ai_training;
CREATE TABLE naryadai_ai_training.dataset_metadata (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);
CREATE TABLE naryadai_ai_training.sites (
    "id" TEXT PRIMARY KEY,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "public_source_id" TEXT NOT NULL,
    "company_site_reference" BOOLEAN NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE)
);
CREATE TABLE naryadai_ai_training.brigades (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "member_ids" JSONB NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE)
);
CREATE TABLE naryadai_ai_training.people (
    "id" TEXT PRIMARY KEY,
    "username" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "job" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "skill_codes" JSONB NOT NULL,
    "grade" INTEGER,
    "brigade_id" TEXT REFERENCES naryadai_ai_training.brigades(id),
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (username),
    CHECK (role IN ('admin', 'manager', 'master', 'worker'))
);
CREATE TABLE naryadai_ai_training.equipment (
    "id" TEXT PRIMARY KEY,
    "site_id" TEXT NOT NULL REFERENCES naryadai_ai_training.sites(id),
    "name" TEXT NOT NULL,
    "inventory_number" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "criticality" TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (inventory_number)
);
CREATE TABLE naryadai_ai_training.materials (
    "id" TEXT PRIMARY KEY,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "unit" TEXT NOT NULL,
    "manufacturer" TEXT,
    "model" TEXT,
    "source_ids" JSONB NOT NULL,
    "reference_data_origin" TEXT NOT NULL,
    "company_usage_confirmed" BOOLEAN NOT NULL,
    "stock_quantity" DOUBLE PRECISION,
    "unit_price" DOUBLE PRECISION,
    "currency" TEXT,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE)
);
CREATE TABLE naryadai_ai_training.fault_codes (
    "id" TEXT PRIMARY KEY,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "source_id" TEXT NOT NULL,
    "company_code_confirmed" BOOLEAN NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (code)
);
CREATE TABLE naryadai_ai_training.work_norms (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "equipment_category" TEXT NOT NULL,
    "fault_code" TEXT NOT NULL REFERENCES naryadai_ai_training.fault_codes(code),
    "expected_minutes" DOUBLE PRECISION NOT NULL,
    "tolerance_ratio" DOUBLE PRECISION NOT NULL,
    "expected_materials" JSONB NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    CHECK (expected_minutes > 0),
    CHECK (tolerance_ratio >= 0)
);
CREATE TABLE naryadai_ai_training.shifts (
    "id" TEXT PRIMARY KEY,
    "site_id" TEXT REFERENCES naryadai_ai_training.sites(id),
    "date" DATE NOT NULL,
    "shift_code" TEXT NOT NULL,
    "starts_at" TIMESTAMPTZ NOT NULL,
    "ends_at" TIMESTAMPTZ NOT NULL,
    "worker_ids" JSONB NOT NULL,
    "master_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE)
);
CREATE TABLE naryadai_ai_training.work_orders (
    "id" TEXT PRIMARY KEY,
    "number" TEXT NOT NULL,
    "site_id" TEXT NOT NULL REFERENCES naryadai_ai_training.sites(id),
    "equipment_id" TEXT NOT NULL REFERENCES naryadai_ai_training.equipment(id),
    "assignee_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    "brigade_id" TEXT NOT NULL REFERENCES naryadai_ai_training.brigades(id),
    "master_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    "shift_id" TEXT NOT NULL REFERENCES naryadai_ai_training.shifts(id),
    "work_norm_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_norms(id),
    "kind" TEXT NOT NULL,
    "priority" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "problem_description" TEXT NOT NULL,
    "required_actions" JSONB NOT NULL,
    "expected_materials" JSONB NOT NULL,
    "fault_code" TEXT NOT NULL REFERENCES naryadai_ai_training.fault_codes(code),
    "issued_at" TIMESTAMPTZ NOT NULL,
    "accepted_at" TIMESTAMPTZ NOT NULL,
    "started_at" TIMESTAMPTZ NOT NULL,
    "due_at" TIMESTAMPTZ NOT NULL,
    "reported_at" TIMESTAMPTZ NOT NULL,
    "closed_at" TIMESTAMPTZ,
    "status" TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (number),
    CHECK (kind IN ('planned', 'unplanned')),
    CHECK (status IN ('closed', 'rework_required'))
);
CREATE TABLE naryadai_ai_training.reports (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "author_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    "submitted_at" TIMESTAMPTZ NOT NULL,
    "performed_work" TEXT NOT NULL,
    "fault_code" TEXT REFERENCES naryadai_ai_training.fault_codes(code),
    "comment" TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (work_order_id)
);
CREATE TABLE naryadai_ai_training.material_usage (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "report_id" TEXT NOT NULL REFERENCES naryadai_ai_training.reports(id),
    "material_id" TEXT NOT NULL REFERENCES naryadai_ai_training.materials(id),
    "quantity" DOUBLE PRECISION NOT NULL,
    "unit" TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    CHECK (quantity >= 0)
);
CREATE TABLE naryadai_ai_training.status_events (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "actor_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    "action" TEXT NOT NULL,
    "from_status" TEXT,
    "to_status" TEXT NOT NULL,
    "occurred_at" TIMESTAMPTZ NOT NULL,
    "comment" TEXT NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE)
);
CREATE TABLE naryadai_ai_training.downtime_intervals (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "equipment_id" TEXT NOT NULL REFERENCES naryadai_ai_training.equipment(id),
    "started_at" TIMESTAMPTZ NOT NULL,
    "ended_at" TIMESTAMPTZ NOT NULL,
    "reason_code" TEXT NOT NULL,
    "planned" BOOLEAN NOT NULL,
    "duration_minutes" DOUBLE PRECISION NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    CHECK (duration_minutes >= 0)
);
CREATE TABLE naryadai_ai_training.photo_evidence (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "report_id" TEXT REFERENCES naryadai_ai_training.reports(id),
    "phase" TEXT NOT NULL,
    "captured_at" TIMESTAMPTZ NOT NULL,
    "author_id" TEXT NOT NULL REFERENCES naryadai_ai_training.people(id),
    "equipment_id" TEXT NOT NULL REFERENCES naryadai_ai_training.equipment(id),
    "attachment_present" BOOLEAN NOT NULL,
    "content_origin" TEXT NOT NULL,
    "image_available" BOOLEAN NOT NULL,
    "photo_verdict" TEXT NOT NULL,
    "manual_review_required" BOOLEAN NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    CHECK (phase IN ('before', 'after')),
    CHECK (content_origin = 'simulated_metadata_only'),
    CHECK (image_available = FALSE),
    CHECK (photo_verdict = 'not_assessed'),
    CHECK (manual_review_required = TRUE)
);
CREATE TABLE naryadai_ai_training.answer_keys (
    "id" TEXT PRIMARY KEY,
    "work_order_id" TEXT NOT NULL REFERENCES naryadai_ai_training.work_orders(id),
    "report_id" TEXT NOT NULL REFERENCES naryadai_ai_training.reports(id),
    "verdict" TEXT NOT NULL,
    "score" DOUBLE PRECISION NOT NULL,
    "issues" JSONB NOT NULL,
    "reasons" JSONB NOT NULL,
    "photo_verdict" TEXT NOT NULL,
    "manual_review_required" BOOLEAN NOT NULL,
    "master_decision_simulated" BOOLEAN NOT NULL,
    synthetic BOOLEAN NOT NULL,
    data_origin TEXT NOT NULL,
    additional_data JSONB NOT NULL,
    CHECK (synthetic = TRUE),
    UNIQUE (work_order_id),
    UNIQUE (report_id),
    CHECK (verdict IN ('accepted', 'accepted_with_remarks', 'rework_required')),
    CHECK (photo_verdict = 'not_assessed'),
    CHECK (manual_review_required = TRUE),
    CHECK (master_decision_simulated = TRUE)
);
CREATE INDEX idx_work_orders_equipment_id_issued_at ON naryadai_ai_training.work_orders (equipment_id, issued_at);
CREATE INDEX idx_reports_work_order_id_submitted_at ON naryadai_ai_training.reports (work_order_id, submitted_at);
CREATE INDEX idx_material_usage_work_order_id_material_id ON naryadai_ai_training.material_usage (work_order_id, material_id);
CREATE INDEX idx_status_events_work_order_id_occurred_at ON naryadai_ai_training.status_events (work_order_id, occurred_at);
CREATE INDEX idx_downtime_intervals_equipment_id_started_at ON naryadai_ai_training.downtime_intervals (equipment_id, started_at);
CREATE INDEX idx_photo_evidence_work_order_id_phase ON naryadai_ai_training.photo_evidence (work_order_id, phase);
CREATE INDEX idx_answer_keys_verdict ON naryadai_ai_training.answer_keys (verdict);
