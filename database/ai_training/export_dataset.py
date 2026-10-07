#!/usr/bin/env python3
"""Export a fictional training package; never connects to an application database.

Only the Python standard library is required. Each equipment unit belongs to one
split. Text examples contain historical observations available before issue time,
and keep simulated acceptance decisions exclusively in the assistant answer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "naryadai_ai_training"
DEFAULT_SEED = "naryadai-synthetic-equipment-split-v1"
VERDICTS = {"accepted", "accepted_with_remarks", "rework_required"}
SYSTEM_PROMPT = (
    "Ты проверяешь закрытие синтетического учебного наряда на ремонт оборудования. "
    "Все сотрудники, оборудование и события в примере вымышлены. Сопоставь факты "
    "отчёта с требованиями наряда, учебным нормативом времени, материалами и метаданными "
    "вложений. Верни JSON с verdict (accepted, accepted_with_remarks или "
    "rework_required), reasons и issues. История содержит только сведения, "
    "доступные до выдачи текущего наряда. Нормативы вымышлены и не утверждены предприятием. "
    "Единые учебные правила: порог принятия — 3 минуты для emergency и 10 для остальных; "
    "ожидание начала свыше 45 минут, длительность меньше 40% или больше 150% норматива "
    "и подача отчёта позже due_at дают замечание. Отличающийся код неисправности даёт "
    "замечание. Пустое или постороннее описание работ, отсутствующий код, лишний материал "
    "или расход сверх количества с допуском из work_order.expected_materials требуют "
    "доработки. Для unplanned обязательна запись о вложении after; для planned она "
    "не обязательна. Если есть основания для доработки, они имеют приоритет над замечаниями. "
    "Фотографий в этом наборе нет: нельзя "
    "оценивать качество ремонта по метаданным. Всегда указывай photo_verdict: "
    "not_assessed и manual_review_required: true. Итог — учебная имитация, "
    "производственное решение принимает уполномоченный мастер."
)


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "text"
    optional: bool = False
    ref: str | None = None
    ref_key: str = "id"


def c(name: str, kind: str = "text", optional: bool = False,
      ref: str | None = None, ref_key: str = "id") -> Column:
    return Column(name, kind, optional, ref, ref_key)


# Arrays represent ordered checklists or declared memberships. Core entities and
# transactional links use typed columns and real foreign keys in both engines.
TABLES: dict[str, tuple[Column, ...]] = {
    "sites": (c("id"), c("code"), c("name"), c("public_source_id"),
              c("company_site_reference", "boolean")),
    "brigades": (c("id"), c("name"), c("member_ids", "json")),
    "people": (
        c("id"), c("username"), c("name"), c("job"), c("role"),
        c("skill_codes", "json"), c("grade", "integer", True),
        c("brigade_id", optional=True, ref="brigades"),
    ),
    "equipment": (
        c("id"), c("site_id", ref="sites"), c("name"), c("inventory_number"),
        c("category"), c("model"), c("criticality"),
    ),
    "materials": (
        c("id"), c("code"), c("name"), c("unit"), c("manufacturer", optional=True),
        c("model", optional=True), c("source_ids", "json"), c("reference_data_origin"),
        c("company_usage_confirmed", "boolean"), c("stock_quantity", "number", True),
        c("unit_price", "number", True), c("currency", optional=True),
    ),
    "fault_codes": (
        c("id"), c("code"), c("name"), c("category"), c("source_id"),
        c("company_code_confirmed", "boolean"),
    ),
    "work_norms": (
        c("id"), c("name"), c("equipment_category"), c("fault_code", ref="fault_codes", ref_key="code"),
        c("expected_minutes", "number"), c("tolerance_ratio", "number"),
        c("expected_materials", "json"),
    ),
    "shifts": (
        c("id"), c("site_id", optional=True, ref="sites"), c("date", "date"),
        c("shift_code"), c("starts_at", "timestamp"), c("ends_at", "timestamp"),
        c("worker_ids", "json"), c("master_id", ref="people"),
    ),
    "work_orders": (
        c("id"), c("number"), c("site_id", ref="sites"),
        c("equipment_id", ref="equipment"), c("assignee_id", ref="people"),
        c("brigade_id", ref="brigades"), c("master_id", ref="people"),
        c("shift_id", ref="shifts"), c("work_norm_id", ref="work_norms"),
        c("kind"), c("priority"), c("title"), c("problem_description"),
        c("required_actions", "json"), c("expected_materials", "json"),
        c("fault_code", ref="fault_codes", ref_key="code"), c("issued_at", "timestamp"),
        c("accepted_at", "timestamp"), c("started_at", "timestamp"),
        c("due_at", "timestamp"), c("reported_at", "timestamp"),
        c("closed_at", "timestamp", True), c("status"),
    ),
    "reports": (
        c("id"), c("work_order_id", ref="work_orders"),
        c("author_id", ref="people"), c("submitted_at", "timestamp"),
        c("performed_work"), c("fault_code", optional=True, ref="fault_codes", ref_key="code"), c("comment"),
    ),
    "material_usage": (
        c("id"), c("work_order_id", ref="work_orders"),
        c("report_id", ref="reports"), c("material_id", ref="materials"),
        c("quantity", "number"), c("unit"),
    ),
    "status_events": (
        c("id"), c("work_order_id", ref="work_orders"),
        c("actor_id", ref="people"), c("action"), c("from_status", optional=True),
        c("to_status"), c("occurred_at", "timestamp"), c("comment"),
    ),
    "downtime_intervals": (
        c("id"), c("work_order_id", ref="work_orders"),
        c("equipment_id", ref="equipment"), c("started_at", "timestamp"),
        c("ended_at", "timestamp"), c("reason_code"), c("planned", "boolean"),
        c("duration_minutes", "number"),
    ),
    "photo_evidence": (
        c("id"), c("work_order_id", ref="work_orders"),
        c("report_id", optional=True, ref="reports"), c("phase"),
        c("captured_at", "timestamp"), c("author_id", ref="people"),
        c("equipment_id", ref="equipment"), c("attachment_present", "boolean"),
        c("content_origin"), c("image_available", "boolean"),
        c("photo_verdict"), c("manual_review_required", "boolean"),
    ),
    "answer_keys": (
        c("id"), c("work_order_id", ref="work_orders"), c("report_id", ref="reports"),
        c("verdict"), c("score", "number"), c("issues", "json"),
        c("reasons", "json"), c("photo_verdict"),
        c("manual_review_required", "boolean"),
        c("master_decision_simulated", "boolean"),
    ),
}

KINDS_PG = {"text": "TEXT", "integer": "INTEGER", "number": "DOUBLE PRECISION",
            "json": "JSONB", "boolean": "BOOLEAN", "timestamp": "TIMESTAMPTZ",
            "date": "DATE"}
KINDS_SQLITE = {"text": "TEXT", "integer": "INTEGER", "number": "REAL",
                "json": "TEXT", "boolean": "INTEGER", "timestamp": "TEXT", "date": "TEXT"}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def _table_constraints(table: str, pg: bool) -> list[str]:
    yes, no = ("TRUE", "FALSE") if pg else ("1", "0")
    constraints = [f"CHECK (synthetic = {yes})"]
    if table == "people":
        constraints += ["UNIQUE (username)",
                        "CHECK (role IN ('admin', 'manager', 'master', 'worker'))"]
    if table == "equipment":
        constraints += ["UNIQUE (inventory_number)"]
    if table == "fault_codes":
        constraints += ["UNIQUE (code)"]
    if table == "work_orders":
        constraints += ["UNIQUE (number)", "CHECK (kind IN ('planned', 'unplanned'))",
                        "CHECK (status IN ('closed', 'rework_required'))"]
    if table == "reports":
        constraints += ["UNIQUE (work_order_id)"]
    if table == "material_usage":
        constraints += ["CHECK (quantity >= 0)"]
    if table == "downtime_intervals":
        constraints += ["CHECK (duration_minutes >= 0)"]
    if table == "work_norms":
        constraints += ["CHECK (expected_minutes > 0)", "CHECK (tolerance_ratio >= 0)"]
    if table == "photo_evidence":
        constraints += ["CHECK (phase IN ('before', 'after'))",
                        "CHECK (content_origin = 'simulated_metadata_only')",
                        f"CHECK (image_available = {no})",
                        "CHECK (photo_verdict = 'not_assessed')",
                        f"CHECK (manual_review_required = {yes})"]
    if table == "answer_keys":
        constraints += ["UNIQUE (work_order_id)", "UNIQUE (report_id)",
                        "CHECK (verdict IN ('accepted', 'accepted_with_remarks', 'rework_required'))",
                        "CHECK (photo_verdict = 'not_assessed')",
                        f"CHECK (manual_review_required = {yes})",
                        f"CHECK (master_decision_simulated = {yes})"]
    return constraints


def schema_sql(pg: bool = True) -> str:
    types = KINDS_PG if pg else KINDS_SQLITE
    prefix = f"{SCHEMA}." if pg else ""
    lines = ["-- SYNTHETIC TRAINING DATA ONLY. Not a production database.",
             "-- All people, inventory units, work orders and decisions are fictional."]
    if pg:
        lines += [f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};"]
    else:
        lines += ["PRAGMA foreign_keys = ON;"]
    lines += [f"CREATE TABLE {prefix}dataset_metadata (",
              "    key TEXT PRIMARY KEY,",
              f"    value {'JSONB' if pg else 'TEXT'} NOT NULL", ");"]
    for table, columns in TABLES.items():
        definitions = []
        for column in columns:
            definition = f'    "{column.name}" {types[column.kind]}'
            if column.name == "id":
                definition += " PRIMARY KEY"
            elif not column.optional:
                definition += " NOT NULL"
            if column.ref:
                definition += f' REFERENCES {prefix}{column.ref}({column.ref_key})'
            definitions.append(definition)
        definitions += [f"    synthetic {'BOOLEAN' if pg else 'INTEGER'} NOT NULL",
                        "    data_origin TEXT NOT NULL",
                        f"    additional_data {'JSONB' if pg else 'TEXT'} NOT NULL"]
        definitions += ["    " + value for value in _table_constraints(table, pg)]
        lines += [f"CREATE TABLE {prefix}{table} (", ",\n".join(definitions), ");"]
    for table, fields in {
        "work_orders": ["equipment_id", "issued_at"],
        "reports": ["work_order_id", "submitted_at"],
        "material_usage": ["work_order_id", "material_id"],
        "status_events": ["work_order_id", "occurred_at"],
        "downtime_intervals": ["equipment_id", "started_at"],
        "photo_evidence": ["work_order_id", "phase"],
        "answer_keys": ["verdict"],
    }.items():
        lines += [f"CREATE INDEX idx_{table}_{'_'.join(fields)} ON {prefix}{table} "
                  f"({', '.join(fields)});"]
    return "\n".join(lines) + "\n"


def normalize_record(table: str, record: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    names = {col.name for col in TABLES[table]} | {"synthetic", "data_origin"}
    for col in TABLES[table]:
        value = record.get(col.name)
        if value is None and not col.optional:
            raise ValueError(f"Missing {table}.{col.name}: {record.get('id')}")
        if value is not None:
            if col.kind in {"text", "timestamp", "date"}:
                if not isinstance(value, str) or "\0" in value:
                    raise ValueError(f"Invalid text {table}.{col.name}")
            elif col.kind == "boolean":
                if not isinstance(value, bool):
                    raise ValueError(f"Invalid boolean {table}.{col.name}")
            elif col.kind in {"integer", "number"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Invalid number {table}.{col.name}")
                if col.kind == "integer" and not isinstance(value, int):
                    raise ValueError(f"Invalid integer {table}.{col.name}")
            elif col.kind == "json":
                dumps(value)
        normalized[col.name] = value
    if record.get("synthetic") is not True:
        raise ValueError(f"Non-synthetic record forbidden in {table}: {record.get('id')}")
    normalized["synthetic"] = True
    normalized["data_origin"] = record.get("data_origin", "synthetic_training")
    normalized["additional_data"] = {k: v for k, v in record.items() if k not in names}
    return normalized


def normalize_dataset(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload.get("metadata"), dict) or payload["metadata"].get("synthetic") is not True:
        raise ValueError("Dataset must explicitly declare metadata.synthetic = true")
    data = {}
    for table in TABLES:
        rows = payload.get(table)
        if not isinstance(rows, list):
            raise ValueError(f"Dataset table must be an array: {table}")
        data[table] = [normalize_record(table, row) for row in rows]
        if len({row["id"] for row in data[table]}) != len(rows):
            raise ValueError(f"Duplicate IDs: {table}")
    for table, columns in TABLES.items():
        for col in columns:
            if col.ref:
                allowed = {row[col.ref_key] for row in data[col.ref]}
                for row in data[table]:
                    if row[col.name] is not None and row[col.name] not in allowed:
                        raise ValueError(f"Dangling FK {table}.{col.name}: {row['id']}")
    return data


def _column_kinds(table: str) -> dict[str, str]:
    return {**{col.name: col.kind for col in TABLES[table]},
            "synthetic": "boolean", "data_origin": "text", "additional_data": "json"}


def _sqlite_value(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "json":
        return dumps(value)
    if kind == "boolean":
        return int(value)
    return value


def write_sqlite(path: Path, data: dict[str, list[dict[str, Any]]], metadata: dict[str, Any]) -> None:
    # A new file is mandatory; the exporter cannot modify a supplied existing DB.
    with path.open("xb"):
        pass
    with sqlite3.connect(path) as connection:
        connection.executescript(schema_sql(False))
        connection.executemany("INSERT INTO dataset_metadata(key, value) VALUES (?, ?)",
                               [(key, dumps(value)) for key, value in metadata.items()])
        for table, rows in data.items():
            kinds = _column_kinds(table)
            names = list(kinds)
            placeholders = ",".join("?" for _ in names)
            quoted = ",".join(f'"{name}"' for name in names)
            connection.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
                                   [tuple(_sqlite_value(row[name], kinds[name]) for name in names)
                                    for row in rows])
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign key check failed")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")


def _pg_value(value: Any, kind: str) -> str:
    if value is None:
        return "NULL"
    if kind == "boolean":
        return "TRUE" if value else "FALSE"
    if kind in {"integer", "number"}:
        return repr(value)
    text_value = dumps(value) if kind == "json" else value
    escaped = text_value.replace("'", "''")
    return f"'{escaped}'" + ("::jsonb" if kind == "json" else "")


def write_postgres(path: Path, data: dict[str, list[dict[str, Any]]], metadata: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("BEGIN;\nSET LOCAL standard_conforming_strings = on;\n")
        handle.write(schema_sql(True))
        for key, value in metadata.items():
            handle.write(f"INSERT INTO {SCHEMA}.dataset_metadata (key, value) VALUES "
                         f"({_pg_value(key, 'text')}, {_pg_value(value, 'json')});\n")
        for table, rows in data.items():
            kinds = _column_kinds(table)
            names = list(kinds)
            quoted = ", ".join(f'"{name}"' for name in names)
            for row in rows:
                values = ", ".join(_pg_value(row[name], kinds[name]) for name in names)
                handle.write(f"INSERT INTO {SCHEMA}.{table} ({quoted}) VALUES ({values});\n")
        handle.write("COMMIT;\n")


def write_csv(directory: Path, data: dict[str, list[dict[str, Any]]]) -> None:
    directory.mkdir()
    for table, rows in data.items():
        kinds = _column_kinds(table)
        with (directory / f"{table}.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(kinds), lineterminator="\n")
            writer.writeheader()
            for row in rows:
                # JSON remains machine-readable; do not evaluate CSV cells as formulas.
                writer.writerow({key: dumps(value) if kinds[key] == "json" else value
                                 for key, value in row.items()})


def split_equipment(equipment_ids: list[str], seed: str) -> dict[str, str]:
    if len(equipment_ids) < 3:
        raise ValueError("At least three equipment groups are required for separate splits")
    ordered = sorted(equipment_ids,
                     key=lambda value: hashlib.sha256(f"{seed}\0{value}".encode()).hexdigest())
    train_count = max(1, int(len(ordered) * 0.7))
    validation_count = max(1, int(len(ordered) * 0.15))
    if train_count + validation_count >= len(ordered):
        train_count = len(ordered) - validation_count - 1
    return {equipment_id: ("train" if i < train_count else
                           "validation" if i < train_count + validation_count else "test")
            for i, equipment_id in enumerate(ordered)}


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _pick(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: record[key] for key in keys if key in record}


ORDER_INPUT = (
    "id", "number", "site_id", "equipment_id",
    "shift_id", "work_norm_id", "kind", "priority", "title", "problem_description",
    "required_actions", "expected_materials", "fault_code", "issued_at", "accepted_at",
    "started_at", "due_at", "reported_at",
)
REPORT_INPUT = ("id", "work_order_id", "submitted_at", "performed_work",
                "fault_code", "comment")
PHOTO_INPUT = ("id", "work_order_id", "report_id", "phase", "captured_at",
               "equipment_id", "attachment_present", "content_origin", "image_available")
FORBIDDEN_INPUT_KEYS = {
    "answer_keys", "verdict", "score", "issues", "reasons", "photo_verdict",
    "manual_review_required", "master_decision_simulated", "closed_at", "status",
    "assignee_id", "author_id", "master_id", "worker_ids", "person_id", "people",
    "username", "job", "brigade_id",
}


def assert_no_target_leakage(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_INPUT_KEYS:
                raise ValueError(f"Label-bearing key found in prompt input: {key}")
            assert_no_target_leakage(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_target_leakage(child)


def build_examples(payload: dict[str, Any], seed: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id = {table: {row["id"]: row for row in payload[table]} for table in TABLES}
    reports = {row["work_order_id"]: row for row in payload["reports"]}
    answers = {row["work_order_id"]: row for row in payload["answer_keys"]}
    if len(reports) != len(payload["reports"]) or len(answers) != len(payload["answer_keys"]):
        raise ValueError("Expected exactly one report and answer per work order")
    usage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    photos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    equipment_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in payload["material_usage"]:
        usage[row["work_order_id"]].append(row)
    for row in payload["photo_evidence"]:
        photos[row["work_order_id"]].append(row)
    for row in payload["work_orders"]:
        equipment_orders[row["equipment_id"]].append(row)
    splits = split_equipment(list(by_id["equipment"]), seed)
    examples = []
    for order in sorted(payload["work_orders"], key=lambda row: (row["issued_at"], row["id"])):
        report, answer = reports.get(order["id"]), answers.get(order["id"])
        if not report or not answer or answer["report_id"] != report["id"]:
            raise ValueError(f"Missing/mismatched report or answer: {order['id']}")
        if answer["verdict"] not in VERDICTS:
            raise ValueError("Unsupported target verdict")
        if not isinstance(answer.get("reasons"), list) or not answer["reasons"]:
            raise ValueError("Every supervised target must have explicit reasons")
        issued_at = _dt(order["issued_at"])
        history = []
        for earlier in sorted(equipment_orders[order["equipment_id"]], key=lambda row: row["issued_at"]):
            previous_report = reports.get(earlier["id"])
            if (earlier["id"] == order["id"] or _dt(earlier["issued_at"]) >= issued_at
                    or not previous_report or _dt(previous_report["submitted_at"]) >= issued_at):
                continue
            history.append({
                "work_order": _pick(earlier, ("id", "equipment_id", "issued_at", "title",
                                             "problem_description", "required_actions", "fault_code")),
                "report": _pick(previous_report, REPORT_INPUT),
            })
        used = usage[order["id"]]
        material_ids = {row["material_id"] for row in used}
        material_ids.update(row["material_id"] for row in order["expected_materials"])
        user_input = {
            "question": "Можно ли закрыть этот учебный наряд? Укажи итог и объясни его по фактам.",
            "work_order": _pick(order, ORDER_INPUT),
            "equipment": _pick(by_id["equipment"][order["equipment_id"]],
                               ("id", "site_id", "name", "inventory_number", "category", "model", "criticality")),
            "report": _pick(report, REPORT_INPUT),
            "material_usage": [_pick(row, ("id", "work_order_id", "report_id", "material_id", "quantity", "unit"))
                               for row in used],
            "material_catalog": [_pick(by_id["materials"][material_id],
                                       ("id", "name", "unit", "manufacturer", "model"))
                                 for material_id in sorted(material_ids)],
            "work_norm": _pick(by_id["work_norms"][order["work_norm_id"]],
                               ("id", "name", "equipment_category", "fault_code", "expected_minutes",
                                "tolerance_ratio", "expected_materials")),
            "shift": _pick(by_id["shifts"][order["shift_id"]],
                           ("id", "site_id", "date", "shift_code", "starts_at", "ends_at")),
            "photo_evidence": [_pick(row, PHOTO_INPUT) for row in photos[order["id"]]],
            "history": history,
        }
        assert_no_target_leakage(user_input)
        assistant = {
            "verdict": answer["verdict"], "reasons": answer["reasons"], "issues": answer["issues"],
            "photo_verdict": "not_assessed", "manual_review_required": True,
        }
        split = splits[order["equipment_id"]]
        examples.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": dumps(user_input)},
                {"role": "assistant", "content": dumps(assistant)},
            ],
            "metadata": {"synthetic": True, "record_id": order["id"],
                         "equipment_id": order["equipment_id"], "split": split},
        })
    partitions = {}
    for split in ("train", "validation", "test"):
        selected = [row for row in examples if row["metadata"]["split"] == split]
        counts = Counter(json.loads(row["messages"][2]["content"])["verdict"] for row in selected)
        partitions[split] = {
            "equipment_ids": sorted(key for key, value in splits.items() if value == split),
            "records": len(selected), "verdict_counts": dict(sorted(counts.items())),
        }
    manifest = {
        "synthetic": True, "seed": seed, "group_key": "equipment_id",
        "ratios_requested": {"train": 0.7, "validation": 0.15, "test": 0.15},
        "partitions": partitions,
        "history_cutoff": "previous work order issued_at and report submitted_at strictly before current issued_at",
        "image_training_ready": False,
        "limitations": ["Synthetic text examples cannot prove quality on real factory data.",
                        "No image pixels or expert-reviewed visual labels are included.",
                        "Reserve test.jsonl for final evaluation; do not train on it."],
    }
    return examples, manifest


def write_jsonl_and_examples(directory: Path, examples: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    for split in ("train", "validation", "test"):
        with (directory / f"{split}.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
            for example in examples:
                if example["metadata"]["split"] == split:
                    handle.write(dumps(example) + "\n")
    (directory / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    selected = []
    for verdict in sorted(VERDICTS):
        sample = next((row for row in examples
                       if json.loads(row["messages"][2]["content"])["verdict"] == verdict), None)
        if sample is not None:
            selected.append(sample)
    lines = ["# Примеры учебных нарядов", "", "Все данные вымышлены. Реальных фотографий здесь нет.", ""]
    for example in selected:
        lines += [f"## {example['metadata']['record_id']} — {example['metadata']['split']}", "",
                  "Вход (без ответа):", "", "```json",
                  json.dumps(json.loads(example["messages"][1]["content"]), ensure_ascii=False, indent=2),
                  "```", "", "Учебный ответ:", "", "```json",
                  json.dumps(json.loads(example["messages"][2]["content"]), ensure_ascii=False, indent=2),
                  "```", ""]
    (directory / "examples_readable.md").write_text("\n".join(lines), encoding="utf-8")


def write_rag(directory: Path, examples: list[dict[str, Any]]) -> None:
    """Write partitioned factual histories, not ground truth answers.

    A full-history document becomes available at its last report timestamp.
    Historical evaluation must filter by that timestamp or use the already
    time-filtered history in JSONL. Raw dataset.json contains answer keys and
    must never be used as a retrieval knowledge source.
    """
    directory.mkdir()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        meta = example["metadata"]
        groups[(meta["split"], meta["equipment_id"])].append(
            json.loads(example["messages"][1]["content"]))
    index = []
    for (split, equipment_id), records in sorted(groups.items()):
        folder = directory / split
        folder.mkdir(exist_ok=True)
        equipment = records[0]["equipment"]
        latest = max(records, key=lambda row: _dt(row["report"]["submitted_at"]))["report"]["submitted_at"]
        lines = [
            f"# {equipment['name']}", "",
            "Синтетическая учебная история. Оборудование и все события вымышлены.", "",
            f"Инвентарный номер: {equipment['inventory_number']}. Категория: {equipment['category']}.",
            f"Модель: {equipment['model']}. Участок: {equipment['site_id']}.", "",
            f"Вся история этого документа доступна начиная с {latest}.",
            "Для ответа на вопрос о прошлом этот полный документ нельзя использовать, если дата "
            "вопроса раньше указанного времени. Для исторической проверки используйте history "
            "в соответствующем JSONL-примере: там сведения уже отфильтрованы по времени.", "",
            "Здесь нет ответов преподавателя, оценок приёмки или изображений. "
            "Метаданные вложений не подтверждают качество ремонта.", "",
        ]
        for record in sorted(records, key=lambda row: _dt(row["work_order"]["issued_at"])):
            order, report, norm = record["work_order"], record["report"], record["work_norm"]
            lines += [f"## {order['number']} — {order['title']}", "",
                      f"ID наряда: {order['id']}. Выдан: {order['issued_at']}. Срок: {order['due_at']}.",
                      f"Вид: {order['kind']}. Приоритет: {order['priority']}. Код неисправности: {order['fault_code']}.",
                      f"Принят исполнителем: {order['accepted_at']}. Начало: {order['started_at']}.", "",
                      f"Заявленная проблема: {order['problem_description']}", "",
                      "Требуемые действия:"]
            lines += [f"- {action}" for action in order["required_actions"]]
            lines += ["", f"Учебный норматив: {norm['name']}, {norm['expected_minutes']} мин; "
                      f"допуск {norm['tolerance_ratio']}. Это вымышленный ориентир, не норматив предприятия.",
                      "", f"Отчёт подан: {report['submitted_at']}.",
                      f"Заявленные выполненные работы: {report['performed_work']}",
                      f"Комментарий исполнителя: {report['comment']}", "", "Материалы в отчёте:"]
            catalog = {item["id"]: item for item in record["material_catalog"]}
            for item in record["material_usage"]:
                lines.append(f"- {catalog[item['material_id']]['name']}: {item['quantity']} {item['unit']}.")
            if not record["material_usage"]:
                lines.append("- Расход не заявлен.")
            lines += ["", "Метаданные вложений:"]
            for item in record["photo_evidence"]:
                lines.append(f"- Этап {item['phase']}; время {item['captured_at']}; "
                             f"наличие заявлено: {item['attachment_present']}; изображения нет.")
            if not record["photo_evidence"]:
                lines.append("- Вложений не заявлено.")
            lines += [""]
        target = folder / f"{equipment_id}.md"
        target.write_text("\n".join(lines), encoding="utf-8")
        index.append({"path": f"{split}/{equipment_id}.md", "equipment_id": equipment_id,
                      "split": split, "synthetic": True, "available_at": latest,
                      "record_ids": [row["work_order"]["id"] for row in records],
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (directory / "index.json").write_text(json.dumps({
        "synthetic": True,
        "history_policy": "Full history: filter documents by available_at for historical questions. "
                          "Use JSONL.history for issue-time snapshots.",
        "ground_truth_included": False, "documents": index,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export(dataset_path: Path, output_dir: Path, seed: str = DEFAULT_SEED) -> dict[str, Any]:
    dataset_path, output_dir = dataset_path.resolve(), output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output directory must be new or empty; existing files are never overwritten")
    payload = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    data = normalize_dataset(payload)
    examples, manifest = build_examples(payload, seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_sqlite(output_dir / "ai_training.sqlite3", data, payload["metadata"])
    write_postgres(output_dir / "postgresql.sql", data, payload["metadata"])
    write_csv(output_dir / "csv", data)
    write_jsonl_and_examples(output_dir, examples, manifest)
    write_rag(output_dir / "rag", examples)
    report = {
        "synthetic": True, "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "table_counts": {table: len(rows) for table, rows in data.items()},
        "jsonl_counts": {split: values["records"] for split, values in manifest["partitions"].items()},
        "postgresql_schema": SCHEMA, "no_production_connection": True,
        "passwords_included": False, "real_work_photos_included": False,
    }
    (output_dir / "export_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--outputdir", type=Path, required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()
    report = export(args.dataset, args.outputdir, args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
