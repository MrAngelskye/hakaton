"""Read-only validation of the isolated, synthetic case 1 training corpus.

Business discrepancies intentionally described by an answer key are examples,
not structural errors. This checker validates their context without requiring
reports to meet the expected norm or to have matching material quantities.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

TABLES = (
    "sites", "people", "brigades", "equipment", "materials", "fault_codes", "work_norms",
    "shifts", "work_orders", "reports", "material_usage", "status_events",
    "downtime_intervals", "photo_evidence", "answer_keys",
)
GROUND_TRUTH_KEYS = {
    "answer_keys", "verdict", "score", "reasons", "issues", "photo_verdict",
    "manual_review_required", "master_decision_simulated", "case_pattern",
    "case_patterns", "expected_verdict", "target", "label", "labels",
    "analytics_flags", "analytics_patterns",
}
SECRET_KEYS = {"password", "password_hash", "password_salt", "pwd", "salt", "token", "api_key"}
IDENTITY_KEYS = {"username", "login", "assignee_id", "author_id", "master_id", "worker_ids", "person_id", "people", "job", "brigade_id"}
TRANSITIONS = {
    None: {"issued"}, "issued": {"accepted"},
    "accepted": {"queued", "in_progress"}, "queued": {"in_progress"},
    "in_progress": {"paused", "completed"}, "paused": {"in_progress"},
    "completed": {"under_review"}, "under_review": {"closed", "rework_required"},
    "closed": set(), "rework_required": set(),
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.statistics: dict[str, Any] = {}

    def require(self, condition: Any, message: str) -> bool:
        if not condition:
            self.errors.append(message)
            return False
        return True

    def result(self) -> dict[str, Any]:
        return {
            "valid": not self.errors, "errors": self.errors,
            "warnings": self.warnings, "statistics": self.statistics,
            "scope": "Synthetic corpus only; no expert judgement or image quality validation.",
        }


def _objects(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child, f"{path}.{key}" if path else str(key)
            yield from _objects(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _objects(child, f"{path}[{index}]")


def _time(value: Any, label: str, result: Validation) -> datetime | None:
    try:
        if not isinstance(value, str):
            raise ValueError("not a string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed
    except (TypeError, ValueError):
        result.errors.append(f"{label}: expected ISO timestamp with timezone")
        return None


def _nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _ordered(values: list[tuple[str, datetime | None]], label: str, result: Validation) -> None:
    known = [(name, value) for name, value in values if value is not None]
    for (first_name, first), (second_name, second) in zip(known, known[1:]):
        result.require(first <= second, f"{label}: {first_name} is after {second_name}")


def validate_dataset(data: Any, exports: Path | None = None) -> dict[str, Any]:
    result = Validation()
    if not result.require(isinstance(data, dict), "dataset: expected an object"):
        return result.result()
    metadata = data.get("metadata", {})
    result.require(isinstance(metadata, dict), "metadata: expected an object")
    if isinstance(metadata, dict):
        result.require(metadata.get("synthetic") is True, "metadata: synthetic must be true")
        result.require(metadata.get("data_origin") == "synthetic_training", "metadata: data_origin must be synthetic_training")
    for key, _, path in _objects(data):
        result.require(str(key).lower() not in SECRET_KEYS, f"{path}: credentials do not belong in a training corpus")

    rows: dict[str, list[dict[str, Any]]] = {}
    indexes: dict[str, dict[str, dict[str, Any]]] = {}
    for table in TABLES:
        supplied = data.get(table)
        if not result.require(isinstance(supplied, list), f"{table}: expected an array"):
            supplied = []
        rows[table] = []
        indexes[table] = {}
        for position, record in enumerate(supplied):
            label = f"{table}[{position}]"
            if not result.require(isinstance(record, dict), f"{label}: expected an object"):
                continue
            ident = record.get("id")
            if not result.require(isinstance(ident, str) and bool(ident.strip()), f"{label}: missing string id"):
                continue
            result.require(ident not in indexes[table], f"{table}: duplicate id {ident}")
            indexes[table][ident] = record
            rows[table].append(record)
            result.require(record.get("synthetic") is True, f"{table}/{ident}: synthetic must be true")
            result.require(record.get("data_origin") == "synthetic_training", f"{table}/{ident}: wrong data_origin")
    result.statistics["counts"] = {table: len(records) for table, records in rows.items()}
    declared_counts = metadata.get("counts", {}) if isinstance(metadata, dict) else {}
    if isinstance(declared_counts, dict):
        for table, count in declared_counts.items():
            if table in rows:
                result.require(count == len(rows[table]), f"metadata.counts.{table}: declared count differs from data")
    else:
        result.errors.append("metadata.counts: expected an object")
    period = metadata.get("period", {}) if isinstance(metadata, dict) else {}
    period_start = _time(period.get("starts_at"), "metadata.period.starts_at", result) if isinstance(period, dict) else None
    period_end = _time(period.get("ends_at"), "metadata.period.ends_at", result) if isinstance(period, dict) else None
    if period_start and period_end:
        result.require(period_start < period_end, "metadata.period: end must follow start")

    def fk(record: dict[str, Any], field: str, target: str, label: str, optional: bool = False):
        value = record.get(field)
        if optional and value is None:
            return None
        if result.require(isinstance(value, str) and value in indexes[target], f"{label}: invalid {field} -> {target}/{value}"):
            return indexes[target][value]
        return None

    usernames = [person.get("username") for person in rows["people"]]
    result.require(all(isinstance(value, str) and value for value in usernames), "people: usernames must be nonempty strings")
    result.require(len(usernames) == len(set(str(value) for value in usernames)), "people: usernames must be unique")
    for person in rows["people"]:
        result.require(person.get("role") in {"worker", "master", "admin", "manager"}, f"people/{person['id']}: invalid role")
        fk(person, "brigade_id", "brigades", f"people/{person['id']}", optional=True)
    for brigade in rows["brigades"]:
        members = brigade.get("member_ids")
        if result.require(isinstance(members, list), f"brigades/{brigade['id']}: expected member_ids array"):
            result.require(len(members) == len(set(str(value) for value in members)), f"brigades/{brigade['id']}: duplicate members")
            for member in members:
                person = indexes["people"].get(str(member))
                result.require(person is not None and person.get("role") == "worker", f"brigades/{brigade['id']}: invalid worker {member}")
                if person:
                    result.require(person.get("brigade_id") == brigade["id"], f"brigades/{brigade['id']}: member {member} has another brigade")
    inventory = [equipment.get("inventory_number") for equipment in rows["equipment"]]
    result.require(all(isinstance(value, str) and bool(value) for value in inventory), "equipment: inventory numbers must be nonempty strings")
    result.require(len(inventory) == len(set(str(value) for value in inventory)), "equipment: inventory numbers must be unique")
    for equipment in rows["equipment"]:
        fk(equipment, "site_id", "sites", f"equipment/{equipment['id']}")
    for material in rows["materials"]:
        result.require(isinstance(material.get("unit"), str) and bool(material.get("unit")), f"materials/{material['id']}: missing unit")
    fault_codes = {record.get("code"): record for record in rows["fault_codes"] if isinstance(record.get("code"), str)}
    result.require(len(fault_codes) == len(rows["fault_codes"]), "fault_codes: codes must be unique nonempty strings")
    result.require(all(bool(code) for code in fault_codes), "fault_codes: code cannot be empty")
    if len(rows["work_orders"]) >= 100:
        result.require(len(fault_codes) >= 20, "fault_codes: at least 20 training fault codes required")
    for table in ("work_norms", "work_orders", "reports"):
        for record in rows[table]:
            code = record.get("fault_code")
            if table == "reports" and code in (None, ""):
                continue  # Missing reported code is an intentional review scenario.
            result.require(code in fault_codes, f"{table}/{record['id']}: unknown fault_code {code}")
    for norm in rows["work_norms"]:
        label = f"work_norms/{norm['id']}"
        result.require(_nonnegative(norm.get("expected_minutes")) and norm.get("expected_minutes", 0) > 0, f"{label}: invalid expected_minutes")
        result.require(_nonnegative(norm.get("tolerance_ratio")), f"{label}: invalid tolerance_ratio")
        for expected in norm.get("expected_materials", []):
            if isinstance(expected, dict):
                material = fk(expected, "material_id", "materials", label)
                result.require(_nonnegative(expected.get("quantity")), f"{label}: invalid expected material quantity")
                if material:
                    result.require(expected.get("unit") == material.get("unit"), f"{label}: expected material unit mismatch")
            else:
                result.errors.append(f"{label}: expected material must be an object")

    shift_times: dict[str, tuple[datetime | None, datetime | None]] = {}
    for shift in rows["shifts"]:
        label = f"shifts/{shift['id']}"
        start = _time(shift.get("starts_at"), f"{label}.starts_at", result)
        end = _time(shift.get("ends_at"), f"{label}.ends_at", result)
        if start and end:
            result.require(start < end, f"{label}: shift must have positive duration")
            result.require((end - start).total_seconds() <= 24 * 3600, f"{label}: shift longer than 24 hours")
        shift_times[shift["id"]] = start, end
        fk(shift, "site_id", "sites", label, optional=True)
        master = fk(shift, "master_id", "people", label)
        if master:
            result.require(master.get("role") == "master", f"{label}: master_id is not a master")
        workers = shift.get("worker_ids")
        if result.require(isinstance(workers, list), f"{label}: worker_ids must be an array"):
            result.require(len(workers) == len(set(str(value) for value in workers)), f"{label}: duplicate workers")
            for worker in workers:
                person = indexes["people"].get(str(worker))
                result.require(person is not None and person.get("role") == "worker", f"{label}: invalid worker {worker}")

    order_times: dict[str, dict[str, datetime | None]] = {}
    worker_intervals: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for order in rows["work_orders"]:
        label = f"work_orders/{order['id']}"
        site = fk(order, "site_id", "sites", label)
        equipment = fk(order, "equipment_id", "equipment", label)
        worker = fk(order, "assignee_id", "people", label)
        brigade = fk(order, "brigade_id", "brigades", label)
        master = fk(order, "master_id", "people", label)
        shift = fk(order, "shift_id", "shifts", label)
        norm = fk(order, "work_norm_id", "work_norms", label)
        if site and equipment:
            result.require(equipment.get("site_id") == site["id"], f"{label}: equipment and work order site differ")
        if worker:
            result.require(worker.get("role") == "worker", f"{label}: assignee is not a worker")
        if master:
            result.require(master.get("role") == "master", f"{label}: responsible person is not a master")
        if brigade and worker:
            result.require(worker["id"] in brigade.get("member_ids", []), f"{label}: assignee not in assigned brigade")
        if norm and equipment:
            result.require(norm.get("equipment_category") == equipment.get("category"), f"{label}: norm and equipment category differ")
        times = {field: _time(order.get(field), f"{label}.{field}", result) for field in ("issued_at", "accepted_at", "started_at", "due_at", "reported_at")}
        times["closed_at"] = _time(order["closed_at"], f"{label}.closed_at", result) if order.get("closed_at") else None
        order_times[order["id"]] = times
        if period_start and period_end:
            for field, timestamp in times.items():
                if timestamp:
                    result.require(period_start <= timestamp <= period_end, f"{label}: {field} outside declared corpus period")
        _ordered([(field, times[field]) for field in ("issued_at", "accepted_at", "started_at", "reported_at", "closed_at")], label, result)
        if times["issued_at"] and times["due_at"]:
            # An intentional delay can put the actual start after the deadline.
            result.require(times["issued_at"] <= times["due_at"], f"{label}: due time precedes issuance")
        if order.get("status") == "closed":
            result.require(times["closed_at"] is not None, f"{label}: closed order has no closed_at")
        elif order.get("status") == "rework_required":
            result.require(times["closed_at"] is None, f"{label}: rework order must remain unclosed")
        else:
            result.errors.append(f"{label}: unexpected final status")
        if shift:
            result.require(order.get("assignee_id") in shift.get("worker_ids", []), f"{label}: worker is not assigned to shift")
            result.require(order.get("master_id") == shift.get("master_id"), f"{label}: shift master mismatch")
            if shift.get("site_id") is not None:
                result.require(order.get("site_id") == shift.get("site_id"), f"{label}: shift site mismatch")
            start, end = shift_times[shift["id"]]
            if start and end:
                for field in ("issued_at", "accepted_at", "started_at", "reported_at"):
                    if times[field]:
                        result.require(start <= times[field] <= end, f"{label}: {field} outside assigned shift")
        if worker and times["started_at"] and times["reported_at"]:
            worker_intervals[worker["id"]].append((times["started_at"], times["reported_at"], order["id"]))
        for expected in order.get("expected_materials", []):
            if isinstance(expected, dict):
                material = fk(expected, "material_id", "materials", label)
                result.require(_nonnegative(expected.get("quantity")), f"{label}: invalid expected quantity")
                result.require(_nonnegative(expected.get("tolerance_ratio")), f"{label}: invalid expected tolerance")
                if material:
                    result.require(expected.get("unit") == material.get("unit"), f"{label}: expected material unit mismatch")
            else:
                result.errors.append(f"{label}: expected material must be an object")
    for worker, intervals in worker_intervals.items():
        intervals.sort()
        running_end = None
        running_id = None
        for start, end, order_id in intervals:
            if running_end is not None:
                result.require(start >= running_end, f"worker/{worker}: overlapping active orders {running_id} and {order_id}")
            if running_end is None or end > running_end:
                running_end, running_id = end, order_id

    reports_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    report_times: dict[str, datetime | None] = {}
    for report in rows["reports"]:
        label = f"reports/{report['id']}"
        order = fk(report, "work_order_id", "work_orders", label)
        fk(report, "author_id", "people", label)
        submitted = _time(report.get("submitted_at"), f"{label}.submitted_at", result)
        report_times[report["id"]] = submitted
        if order:
            reports_by_order[order["id"]].append(report)
            result.require(report.get("author_id") == order.get("assignee_id"), f"{label}: author is not order assignee")
            result.require(submitted == order_times[order["id"]]["reported_at"], f"{label}: submission and order reported_at differ")
    for order in rows["work_orders"]:
        result.require(len(reports_by_order[order["id"]]) == 1, f"work_orders/{order['id']}: expected exactly one report")

    for usage in rows["material_usage"]:
        label = f"material_usage/{usage['id']}"
        order = fk(usage, "work_order_id", "work_orders", label)
        report = fk(usage, "report_id", "reports", label)
        material = fk(usage, "material_id", "materials", label)
        result.require(_nonnegative(usage.get("quantity")), f"{label}: quantity must be finite and nonnegative")
        if report and order:
            result.require(report.get("work_order_id") == order["id"], f"{label}: report belongs to another order")
        if material:
            result.require(usage.get("unit") == material.get("unit"), f"{label}: material unit mismatch")

    events_by_order: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for event in rows["status_events"]:
        label = f"status_events/{event['id']}"
        order = fk(event, "work_order_id", "work_orders", label)
        fk(event, "actor_id", "people", label)
        occurred = _time(event.get("occurred_at"), f"{label}.occurred_at", result)
        if order and occurred:
            events_by_order[order["id"]].append((occurred, event))
    for order in rows["work_orders"]:
        label = f"work_orders/{order['id']}"
        events = events_by_order[order["id"]]
        result.require(bool(events), f"{label}: missing status history")
        if events:
            result.require([time for time, _ in events] == sorted(time for time, _ in events), f"{label}: status events are not chronological")
            previous = None
            for occurred, event in events:
                result.require(event.get("from_status") == previous, f"{label}: broken status transition at {event['id']}")
                result.require(isinstance(event.get("to_status"), str) and bool(event.get("to_status")), f"{label}: invalid to_status")
                result.require(event.get("to_status") in TRANSITIONS.get(previous, set()), f"{label}: unsupported lifecycle transition at {event['id']}")
                previous = event.get("to_status")
                issued = order_times[order["id"]]["issued_at"]
                if issued:
                    result.require(occurred >= issued, f"{label}: status event before issuance")
            result.require(previous == order.get("status"), f"{label}: final history status differs from order")

    for interval in rows["downtime_intervals"]:
        label = f"downtime_intervals/{interval['id']}"
        order = fk(interval, "work_order_id", "work_orders", label)
        equipment = fk(interval, "equipment_id", "equipment", label)
        start = _time(interval.get("started_at"), f"{label}.started_at", result)
        end = _time(interval.get("ended_at"), f"{label}.ended_at", result)
        minutes = interval.get("duration_minutes")
        result.require(_nonnegative(minutes), f"{label}: invalid duration_minutes")
        if start and end:
            result.require(end >= start, f"{label}: negative interval")
            if _nonnegative(minutes):
                result.require(abs((end - start).total_seconds() / 60 - minutes) < 0.001, f"{label}: duration_minutes does not match timestamps")
        if order and equipment:
            result.require(order.get("equipment_id") == equipment["id"], f"{label}: equipment differs from order")

    for photo in rows["photo_evidence"]:
        label = f"photo_evidence/{photo['id']}"
        order = fk(photo, "work_order_id", "work_orders", label)
        report = fk(photo, "report_id", "reports", label, optional=True)
        fk(photo, "author_id", "people", label)
        fk(photo, "equipment_id", "equipment", label)
        _time(photo.get("captured_at"), f"{label}.captured_at", result)
        result.require(photo.get("phase") in {"before", "after"}, f"{label}: invalid phase")
        result.require(photo.get("content_origin") == "simulated_metadata_only", f"{label}: must be simulated metadata, not a factual image")
        result.require(photo.get("image_available") is False, f"{label}: no real images were generated or verified")
        result.require(photo.get("photo_verdict") == "not_assessed", f"{label}: image quality must not be fabricated")
        result.require(photo.get("manual_review_required") is True, f"{label}: human review flag required")
        for field in ("original_url", "source_url", "image_url", "file_path", "relative_path", "paired_photo_id"):
            result.require(photo.get(field) in (None, ""), f"{label}: real photo reference or fabricated pair is forbidden")
        if order and report:
            result.require(report.get("work_order_id") == order["id"], f"{label}: report belongs to another order")

    keys_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scores, verdicts, issue_codes = set(), Counter(), Counter()
    for answer in rows["answer_keys"]:
        label = f"answer_keys/{answer['id']}"
        order = fk(answer, "work_order_id", "work_orders", label)
        report = fk(answer, "report_id", "reports", label)
        if order:
            keys_by_order[order["id"]].append(answer)
        if order and report:
            result.require(report.get("work_order_id") == order["id"], f"{label}: report belongs to another order")
        verdict = answer.get("verdict")
        result.require(isinstance(verdict, str) and bool(verdict), f"{label}: missing verdict")
        verdicts[str(verdict)] += 1
        score = answer.get("score")
        result.require(_nonnegative(score) and score <= 100, f"{label}: score must be between 0 and 100")
        if _nonnegative(score):
            scores.add(score)
        reasons = answer.get("reasons")
        result.require(isinstance(reasons, list) and bool(reasons) and all(isinstance(reason, str) and reason.strip() for reason in reasons), f"{label}: reasons must be nonempty strings")
        issues = answer.get("issues")
        if result.require(isinstance(issues, list), f"{label}: issues must be an array"):
            for issue in issues:
                if result.require(isinstance(issue, dict), f"{label}: issue must be an object"):
                    result.require(isinstance(issue.get("code"), str) and bool(issue.get("code")), f"{label}: issue code missing")
                    result.require(isinstance(issue.get("explanation"), str) and bool(issue.get("explanation")), f"{label}: issue explanation missing")
                    result.require(isinstance(issue.get("evidence_fields"), list) and bool(issue.get("evidence_fields")), f"{label}: issue evidence fields missing")
                    issue_codes[str(issue.get("code"))] += 1
        result.require(answer.get("photo_verdict") == "not_assessed", f"{label}: no real image verdict can be asserted")
        result.require(answer.get("manual_review_required") is True, f"{label}: master review required")
        result.require(answer.get("master_decision_simulated") is True, f"{label}: decision must be marked simulated")
    for order in rows["work_orders"]:
        result.require(len(keys_by_order[order["id"]]) == 1, f"work_orders/{order['id']}: expected exactly one answer key")
    if len(rows["work_orders"]) >= 100:
        result.require(len(scores) >= 3, "answer_keys: a single default score cannot represent the corpus")
        result.require(len(verdicts) >= 2, "answer_keys: missing contrasting verdict examples")
        result.require(len(issue_codes) >= 5, "answer_keys: insufficient discrepancy pattern coverage")
    result.statistics["verdicts"] = dict(sorted(verdicts.items()))
    result.statistics["issue_codes"] = dict(sorted(issue_codes.items()))
    result.statistics["distinct_scores"] = sorted(scores)
    result.statistics["active_work_interval"] = "started_at <= t < reported_at; rework waiting does not lock a worker"
    normalized = {"metadata": metadata if isinstance(metadata, dict) else {}, **rows}
    _validate_answer_evidence(normalized, indexes, order_times, keys_by_order, result)
    _validate_analytics(normalized, indexes, order_times, keys_by_order, result)
    if exports is not None:
        _validate_exports(exports, normalized, indexes, order_times, report_times, keys_by_order, result)
    return result.result()


def _validate_answer_evidence(data, indexes, times, keys_by_order, result: Validation) -> None:
    """Recalculate observable discrepancy rules without importing the generator."""
    rework_codes = {"missing_after_photo", "empty_report", "work_mismatch", "wrong_material", "excess_material", "missing_fault_code"}
    remarks_codes = {"fault_code_mismatch", "overdue", "slow_acceptance", "very_short_duration", "long_duration", "shift_delay"}
    quantitative_codes = (rework_codes | remarks_codes) - {"empty_report", "work_mismatch"}
    reports = {report.get("work_order_id"): report for report in data["reports"]}
    usage_by_order = defaultdict(list)
    photos_by_order = defaultdict(list)
    for usage in data["material_usage"]:
        usage_by_order[usage.get("work_order_id")].append(usage)
    for photo in data["photo_evidence"]:
        photos_by_order[photo.get("work_order_id")].append(photo)
    checked = 0
    for order in data["work_orders"]:
        answers = keys_by_order.get(order["id"], [])
        report = reports.get(order["id"])
        norm = indexes["work_norms"].get(order.get("work_norm_id"))
        if not answers or not report or not norm:
            continue
        answer = answers[0]
        label = f"answer_keys/{answer['id']}"
        issue_rows = answer.get("issues", [])
        if not isinstance(issue_rows, list) or not all(isinstance(issue, dict) for issue in issue_rows):
            continue
        actual_codes = {issue.get("code") for issue in issue_rows}
        result.require(len(actual_codes) == len(issue_rows), f"{label}: duplicate issue codes")
        result.require(actual_codes <= rework_codes | remarks_codes, f"{label}: unsupported issue classification")
        expected = set()
        order_time = times[order["id"]]
        if all(order_time.get(field) for field in ("issued_at", "accepted_at", "started_at", "reported_at", "due_at")) and _nonnegative(norm.get("expected_minutes")):
            reaction = (order_time["accepted_at"] - order_time["issued_at"]).total_seconds() / 60
            duration = (order_time["reported_at"] - order_time["started_at"]).total_seconds() / 60
            delay = (order_time["started_at"] - order_time["accepted_at"]).total_seconds() / 60
            if order_time["reported_at"] > order_time["due_at"]:
                expected.add("overdue")
            if reaction > (3 if order.get("priority") == "emergency" else 10):
                expected.add("slow_acceptance")
            if duration < norm["expected_minutes"] * 0.4:
                expected.add("very_short_duration")
            if duration > norm["expected_minutes"] * 1.5:
                expected.add("long_duration")
            if delay > 45:
                expected.add("shift_delay")
        if not report.get("fault_code"):
            expected.add("missing_fault_code")
        elif report.get("fault_code") != order.get("fault_code"):
            expected.add("fault_code_mismatch")
        if order.get("kind") == "unplanned" and not any(photo.get("phase") == "after" and photo.get("attachment_present") is True for photo in photos_by_order[order["id"]]):
            expected.add("missing_after_photo")
        specifications = {item.get("material_id"): item for item in order.get("expected_materials", []) if isinstance(item, dict)}
        amounts = defaultdict(float)
        for used in usage_by_order[order["id"]]:
            material_id, quantity = used.get("material_id"), used.get("quantity")
            if material_id not in specifications:
                expected.add("wrong_material")
            if _nonnegative(quantity):
                amounts[material_id] += quantity
        for material_id, specification in specifications.items():
            if _nonnegative(specification.get("quantity")) and _nonnegative(specification.get("tolerance_ratio")):
                if amounts[material_id] > specification["quantity"] * (1 + specification["tolerance_ratio"]) + 1e-8:
                    expected.add("excess_material")
        result.require(actual_codes & quantitative_codes == expected, f"{label}: issue labels are unsupported by observable time/material/fault/photo metadata")
        performed = report.get("performed_work", "")
        if "empty_report" in actual_codes:
            result.require(isinstance(performed, str) and len(performed.strip()) < 45, f"{label}: empty_report label has a substantial description")
        if "work_mismatch" in actual_codes:
            equipment = indexes["equipment"].get(order.get("equipment_id"), {})
            result.require(isinstance(performed, str) and len(performed.strip()) >= 45 and equipment.get("inventory_number", "") not in performed, f"{label}: work_mismatch has no distinguishable unrelated-task evidence")
        severe = bool(actual_codes & rework_codes)
        expected_verdict = "rework_required" if severe else "accepted_with_remarks" if actual_codes else "accepted"
        result.require(answer.get("verdict") == expected_verdict, f"{label}: verdict contradicts issue severity")
        expected_score = max(15, 96 - 28 * len(actual_codes & rework_codes) - 9 * len(actual_codes & remarks_codes))
        if severe:
            expected_score = min(expected_score, 60)
        result.require(answer.get("score") == expected_score, f"{label}: rule score contradicts documented issue penalties")
        result.require(order.get("status") == ("rework_required" if severe else "closed"), f"{label}: simulated workflow decision contradicts evidence verdict")
        for issue in issue_rows:
            expected_severity = "rework" if issue.get("code") in rework_codes else "remarks"
            result.require(issue.get("severity") == expected_severity, f"{label}: issue severity contradicts discrepancy class")
        if issue_rows:
            result.require(answer.get("reasons") == [issue.get("explanation") for issue in issue_rows], f"{label}: reasons do not describe classified issues")
        checked += 1
    result.statistics["answer_keys_with_recalculated_evidence"] = checked


def _validate_analytics(data, indexes, times, keys_by_order, result: Validation) -> None:
    patterns = data.get("metadata", {}).get("analytics_patterns", [])
    if not isinstance(patterns, list):
        result.errors.append("metadata.analytics_patterns: expected an array")
        return
    by_code = {pattern.get("code"): pattern for pattern in patterns if isinstance(pattern, dict)}
    expected_codes = {"frequent_conveyor_failure", "worker_rework_rate", "repeat_fault_within_14_days", "shift_downtime_difference"}
    result.require(set(by_code) == expected_codes and len(patterns) == 4, "metadata.analytics_patterns: exactly four distinct analytics patterns required")
    counts = Counter(order.get("equipment_id") for order in data["work_orders"] if order.get("kind") == "unplanned")
    recomputed = {}
    for code, pattern in by_code.items():
        label = f"analytics/{code}"
        result.require(pattern.get("causality_established") is False, f"{label}: statistics must not assert causality")
        calculated = {}
        if code == "frequent_conveyor_failure":
            target = indexes["equipment"].get(pattern.get("equipment_id"))
            if not result.require(target is not None, f"{label}: invalid target equipment"):
                continue
            peers = {equipment["id"] for equipment in data["equipment"] if equipment.get("category") == target.get("category") and equipment["id"] != target["id"]}
            result.require(set(pattern.get("peer_equipment_ids", [])) == peers, f"{label}: peer group differs from equipment category")
            average = sum(counts[ident] for ident in peers) / len(peers) if peers else 0
            calculated = {"unplanned_count": counts[target["id"]], "peer_mean_unplanned_count": round(average, 4), "ratio_to_peer_mean": round(counts[target["id"]] / average, 4) if average else None}
        elif code == "worker_rework_rate":
            target = pattern.get("person_id")
            result.require(target in indexes["people"], f"{label}: invalid target person")
            own_orders = [order for order in data["work_orders"] if order.get("assignee_id") == target]
            other_orders = [order for order in data["work_orders"] if order.get("assignee_id") != target]
            def rework(orders):
                return sum(bool(keys_by_order.get(order["id"])) and keys_by_order[order["id"]][0].get("verdict") == "rework_required" for order in orders)
            bad, others_bad = rework(own_orders), rework(other_orders)
            calculated = {"orders_count": len(own_orders), "rework_count": bad, "rework_rate": round(bad / len(own_orders), 4) if own_orders else None, "others_rework_rate": round(others_bad / len(other_orders), 4) if other_orders else None}
        elif code == "repeat_fault_within_14_days":
            target = pattern.get("equipment_id")
            result.require(target in indexes["equipment"], f"{label}: invalid target equipment")
            flagged = 0
            for order in data["work_orders"]:
                if order.get("equipment_id") != target or order.get("kind") != "unplanned" or not times[order["id"]].get("issued_at"):
                    continue
                issued = times[order["id"]]["issued_at"]
                if any(old.get("equipment_id") == target and old.get("kind") == "unplanned" and old.get("fault_code") == order.get("fault_code")
                       and times[old["id"]].get("reported_at") and 0 < (issued - times[old["id"]]["reported_at"]).total_seconds() <= 14 * 86400
                       for old in data["work_orders"]):
                    flagged += 1
            calculated = {"flagged_orders_count": flagged, "lookback_days": 14}
        elif code == "shift_downtime_difference":
            values = defaultdict(list)
            for interval in data["downtime_intervals"]:
                order = indexes["work_orders"].get(interval.get("work_order_id"))
                shift = indexes["shifts"].get(order.get("shift_id")) if order else None
                if shift and _nonnegative(interval.get("duration_minutes")):
                    values[shift.get("shift_code")].append(interval["duration_minutes"])
            calculated = {"by_shift": {shift: {"interval_count": len(durations), "mean_minutes": round(sum(durations) / len(durations), 4), "long_intervals_count": sum(duration > 150 for duration in durations)} for shift, durations in sorted(values.items())}}
        for field, expected in calculated.items():
            result.require(pattern.get(field) == expected, f"{label}: {field} differs from independent recalculation")
        recomputed[code] = calculated
    result.statistics["recalculated_analytics"] = recomputed


def _validate_exports(directory: Path, data: dict[str, Any], indexes, order_times, report_times, keys_by_order, result: Validation) -> None:
    try:
        manifest = json.loads((directory / "split_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result.errors.append(f"exports/split_manifest.json: cannot read ({exc})")
        return
    partitions = manifest.get("partitions", {})
    assigned_equipment: dict[str, str] = {}
    seen_records: dict[str, str] = {}
    split_counts = {}
    identities = [str(person[field]) for person in data["people"] for field in ("name", "username") if person.get(field)]
    for split in ("train", "validation", "test"):
        partition = partitions.get(split, {})
        equipment_ids = partition.get("equipment_ids", [])
        if not result.require(isinstance(equipment_ids, list), f"exports/{split}: equipment_ids must be an array"):
            equipment_ids = []
        result.require(len(equipment_ids) == len(set(str(value) for value in equipment_ids)), f"exports/{split}: duplicate equipment in split manifest")
        for equipment_id in equipment_ids:
            result.require(equipment_id in indexes["equipment"], f"exports/{split}: unknown equipment {equipment_id}")
            result.require(equipment_id not in assigned_equipment, f"exports: equipment overlap between splits for {equipment_id}")
            assigned_equipment[str(equipment_id)] = split
        jsonl = directory / f"{split}.jsonl"
        count = 0
        try:
            lines = jsonl.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            result.errors.append(f"exports/{split}: cannot read JSONL ({exc})")
            continue
        for line_number, line in enumerate(lines, 1):
            label = f"exports/{split}.jsonl:{line_number}"
            if not line.strip():
                result.errors.append(f"{label}: blank JSONL record")
                continue
            try:
                record = json.loads(line)
                messages = record["messages"]
                result.require([message.get("role") for message in messages] == ["system", "user", "assistant"], f"{label}: expected system, user, assistant messages")
                user = json.loads(next(message["content"] for message in messages if message.get("role") == "user"))
                assistant = json.loads(next(message["content"] for message in messages if message.get("role") == "assistant"))
                extra = record["metadata"]
                ident = extra["record_id"]
                order = indexes["work_orders"][ident]
            except (ValueError, KeyError, TypeError, StopIteration) as exc:
                result.errors.append(f"{label}: malformed JSONL record ({exc})")
                continue
            count += 1
            result.require(ident not in seen_records, f"{label}: duplicate training record {ident}")
            seen_records[ident] = split
            result.require(extra.get("split") == split, f"{label}: split metadata mismatch")
            result.require(extra.get("synthetic") is True, f"{label}: synthetic metadata required")
            result.require(extra.get("equipment_id") == order.get("equipment_id"), f"{label}: equipment metadata mismatch")
            result.require(order.get("equipment_id") in equipment_ids, f"{label}: order equipment not in this split")
            for key, _, field_path in _objects(user):
                result.require(str(key).lower() not in GROUND_TRUTH_KEYS, f"{label}: ground truth leaks into user input at {field_path}")
                result.require(str(key).lower() not in SECRET_KEYS, f"{label}: secret in user input at {field_path}")
                result.require(str(key).lower() not in IDENTITY_KEYS, f"{label}: worker identity leaks into quality-checker input at {field_path}")
            serialized_input = json.dumps(user, ensure_ascii=False)
            result.require(not any(identity in serialized_input for identity in identities), f"{label}: a person's name or username leaked into quality-checker input")
            input_order = user.get("work_order", {})
            result.require(input_order.get("id") == ident, f"{label}: input order id mismatch")
            result.require("status" not in input_order and "closed_at" not in input_order, f"{label}: final status leaks into input")
            result.require(user.get("equipment", {}).get("id") == order.get("equipment_id"), f"{label}: input equipment mismatch")
            supplied_report = user.get("report", {})
            report = indexes["reports"].get(supplied_report.get("id"))
            result.require(report is not None and report.get("work_order_id") == ident, f"{label}: input report does not belong to order")
            for historical in user.get("history", []):
                if not isinstance(historical, dict):
                    result.errors.append(f"{label}: history item must be an object")
                    continue
                past_order = indexes["work_orders"].get(historical.get("work_order", {}).get("id"))
                past_report = indexes["reports"].get(historical.get("report", {}).get("id"))
                if result.require(past_order is not None and past_report is not None, f"{label}: unknown historical order/report"):
                    result.require(past_report.get("work_order_id") == past_order["id"], f"{label}: history report/order mismatch")
                    result.require(past_order.get("equipment_id") == order.get("equipment_id"), f"{label}: history from another equipment")
                    past_time = report_times.get(past_report["id"])
                    issued = order_times[ident]["issued_at"]
                    if past_time and issued:
                        result.require(past_time < issued, f"{label}: future or same-order history leakage")
                    result.require(historical.get("report", {}).get("submitted_at") == past_report.get("submitted_at"), f"{label}: historical timestamp was altered")
                    result.require("status" not in historical.get("work_order", {}) and "closed_at" not in historical.get("work_order", {}), f"{label}: historical final status leaks into input")
            answers = keys_by_order.get(ident, [])
            if answers:
                answer = answers[0]
                for field in ("verdict", "reasons", "issues", "photo_verdict", "manual_review_required"):
                    result.require(assistant.get(field) == answer.get(field), f"{label}: assistant {field} differs from isolated answer key")
        split_counts[split] = count
        expected_records = partition.get("records")
        if isinstance(expected_records, int):
            result.require(count == expected_records, f"exports/{split}: record count differs from manifest")
        elif isinstance(expected_records, list):
            result.require(set(expected_records) == {ident for ident, assigned in seen_records.items() if assigned == split}, f"exports/{split}: manifest record ids mismatch")
        else:
            result.errors.append(f"exports/{split}: manifest records must be count or id array")
    result.require(set(seen_records) == set(indexes["work_orders"]), "exports: work order coverage differs from dataset")
    result.statistics["split_records"] = split_counts
    result.statistics["split_equipment"] = dict(Counter(assigned_equipment.values()))

    rag_directory = directory / "rag"
    if rag_directory.exists():
        try:
            rag_index = json.loads((rag_directory / "index.json").read_text(encoding="utf-8"))
            result.require(rag_index.get("ground_truth_included") is False, "exports/RAG: ground truth must not be included")
            seen_rag_equipment = set()
            for document in rag_index["documents"]:
                label = f"exports/RAG/{document.get('path')}"
                relative = Path(document["path"])
                if not result.require(not relative.is_absolute() and ".." not in relative.parts, f"{label}: unsafe document path"):
                    continue
                split, equipment_id = document.get("split"), document.get("equipment_id")
                result.require(assigned_equipment.get(equipment_id) == split, f"{label}: document crosses equipment split")
                result.require(relative.parts[0] == split, f"{label}: directory split mismatch")
                result.require(equipment_id not in seen_rag_equipment, f"{label}: duplicate equipment document")
                seen_rag_equipment.add(equipment_id)
                content = (rag_directory / relative).read_bytes()
                result.require(hashlib.sha256(content).hexdigest() == document.get("sha256"), f"{label}: document hash mismatch")
                text = content.decode("utf-8")
                result.require(not any(identity in text for identity in identities), f"{label}: person's identity leaked into RAG")
                own_records = [order for order in indexes["work_orders"].values() if order.get("equipment_id") == equipment_id]
                result.require(set(document.get("record_ids", [])) == {order["id"] for order in own_records}, f"{label}: order coverage mismatch")
                available = _time(document.get("available_at"), f"{label}.available_at", result)
                known_report_times = [report_times[report["id"]] for report in indexes["reports"].values()
                                      if report.get("work_order_id") in document.get("record_ids", [])]
                if available and known_report_times and all(known_report_times):
                    result.require(available == max(known_report_times), f"{label}: availability time excludes later report evidence")
                for foreign_order in indexes["work_orders"].values():
                    if foreign_order.get("equipment_id") != equipment_id:
                        result.require(foreign_order["id"] not in text, f"{label}: includes facts of another equipment split")
                for key in ("answer_keys", "master_decision_simulated", '"verdict"', '"issues"', '"score"'):
                    result.require(key not in text, f"{label}: contains a ground truth label")
            result.require(seen_rag_equipment == set(assigned_equipment), "exports/RAG: equipment coverage differs from split manifest")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.errors.append(f"exports/RAG: cannot validate ({exc})")

    database = directory / "ai_training.sqlite3"
    if database.exists():
        try:
            with sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as connection:
                result.require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "exports/SQLite: integrity check failed")
                result.require(not connection.execute("PRAGMA foreign_key_check").fetchall(), "exports/SQLite: foreign key check failed")
                for table in TABLES:
                    count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    result.require(count == len(data[table]), f"exports/SQLite/{table}: count differs from source dataset")
        except sqlite3.Error as exc:
            result.errors.append(f"exports/SQLite: cannot validate ({exc})")
    for table in TABLES:
        csv_path = directory / "csv" / f"{table}.csv"
        if csv_path.exists():
            try:
                with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                    exported = list(csv.DictReader(stream))
                result.require(len(exported) == len(data[table]), f"exports/CSV/{table}: count differs from source dataset")
            except (OSError, csv.Error) as exc:
                result.errors.append(f"exports/CSV/{table}: cannot validate ({exc})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("dataset.json"))
    parser.add_argument("--exports", type=Path)
    parser.add_argument("--report", type=Path, help="Write validation report JSON; dataset and exports remain read-only")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.dataset.read_text(encoding="utf-8"))
        report = validate_dataset(data, args.exports)
    except (OSError, ValueError) as exc:
        report = {"valid": False, "errors": [f"dataset: cannot read ({exc})"], "warnings": [], "statistics": {}}
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
