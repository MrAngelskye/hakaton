"""Build an isolated, reproducible synthetic training history for case 1.

This module never opens the application DB, changes accounts, or stores passwords.
The resulting labels are deterministic teaching rules, not expert annotations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import uuid

from scenarios import EXTRA_MATERIALS, ISSUE_DEFINITIONS, SCENARIOS

SEED = 20261008
START = date(2026, 7, 8)
END = date(2026, 10, 7)
TZ = timezone(timedelta(hours=5))
COLLECTIONS = ("sites", "people", "brigades", "equipment", "materials", "fault_codes", "work_norms",
               "shifts", "work_orders", "reports", "material_usage", "status_events",
               "downtime_intervals", "photo_evidence", "answer_keys")
ORIGIN = {"synthetic": True, "data_origin": "synthetic_training"}


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def syn(**values):
    return {**values, **ORIGIN}


class Builder:
    def __init__(self, catalog: dict, seed: int):
        self.catalog = catalog
        self.seed = seed
        self.random = random.Random(seed)
        self.data = {name: [] for name in COLLECTIONS}
        self.person_by_username = {}
        self.material_by_code = {}
        self.norm_by_key = {}
        self.shift_by_person_day = {}
        self.worker_busy_until = {}
        self.equipment_busy_until = {}

    def identifier(self) -> str:
        # Random-looking, stable IDs do not encode the verdict or scenario class.
        return "SYN-" + uuid.UUID(int=self.random.getrandbits(128), version=4).hex

    def add(self, table, **values):
        item = syn(id=self.identifier(), **values)
        self.data[table].append(item)
        return item

    def build_references(self):
        for item in self.catalog["sites"]:
            self.add("sites", code=item["code"], name=item["name"],
                     public_source_id=item["source_id"], company_site_reference=True,
                     note="Название из открытого источника; связь с учебными объектами вымышлена.")
        for item in self.catalog["defect_codes"]:
            self.add("fault_codes", code=item["code"], name=item["name"], category=item["category"],
                     source_id=item["source_id"], company_code_confirmed=False)
        brigades = [self.add("brigades", name=f"Учебная бригада {n}", member_ids=[])
                    for n in range(1, 4)]
        skills = {
            1: ["mechanical", "electrical"], 2: ["electrical"], 3: ["instrumentation"],
            4: ["mechanical"], 5: ["welding"], 6: ["machining"], 7: ["rail"],
            8: ["loader"], 9: ["automotive"], 10: ["rail_maintenance"],
            11: ["mechanical", "electrical"], 12: ["electrical"],
            13: ["instrumentation"], 14: ["mechanical"], 15: ["welding"],
        }
        for account in self.catalog["accounts"]:
            is_worker = account["role"] == "worker"
            n = int(account["username"].rsplit(".", 1)[-1]) if is_worker else None
            brigade = brigades[(n - 1) // 5] if is_worker else None
            p = self.add("people", username=account["username"], name=account["name"],
                         job=account["job"], role=account["role"],
                         skill_codes=skills[n] if is_worker else [],
                         grade=self.random.choice([4, 5, 6]) if is_worker else None,
                         brigade_id=brigade["id"] if brigade else None,
                         identity_origin="fictional", qualification_origin="synthetic_assumption",
                         company_employee_confirmed=False)
            self.person_by_username[p["username"]] = p
            if brigade:
                brigade["member_ids"].append(p["id"])
        for source in self.catalog["materials"]:
            m = self.add("materials", code=source["code"], name=source["name"],
                         unit=source["unit"], manufacturer=source.get("manufacturer"),
                         model=source.get("model"), source_ids=source.get("source_ids", [source["source_id"]]),
                         reference_data_origin="verified_public_manufacturer_reference",
                         company_usage_confirmed=False, stock_quantity=None,
                         unit_price=None, currency=None,
                         note="Каталоговая позиция; совместимость и расход в учебных нарядах вымышлены.")
            self.material_by_code[m["code"]] = m
        for code, name, unit in EXTRA_MATERIALS:
            m = self.add("materials", code=code, name=name, unit=unit, manufacturer=None,
                         model=None, source_ids=[], reference_data_origin="fictional_training_catalogue",
                         company_usage_confirmed=False, stock_quantity=None, unit_price=None,
                         currency=None, note="Вымышленная позиция только для учебной модели.")
            self.material_by_code[code] = m
        for s in SCENARIOS:
            expected = [self.expected_material(code, quantity) for code, quantity in s["materials"]]
            norm = self.add("work_norms", name=s["title"], equipment_category=s["category"],
                            fault_code=s["fault_code"], expected_minutes=s["minutes"],
                            tolerance_ratio=0.25, expected_materials=expected,
                            norm_origin="fictional_teaching_assumption",
                            engineering_approval=False)
            self.norm_by_key[s["key"]] = norm
        categories = [
            ["Погрузчик"] * 4 + ["Подвижной состав"] * 4 + ["Конвейер"] * 4 +
            ["Подшипниковый узел"] * 2 + ["Редуктор"] * 2,
            ["Конвейер"] * 4 + ["Насос"] * 3 + ["Дробильное оборудование"] * 3 +
            ["Редуктор"] * 2 + ["Подшипниковый узел"] * 2 + ["Сварное соединение"] * 2,
            ["Автотранспорт"] * 5 + ["Погрузчик"] * 3 + ["Насос"] * 2 +
            ["Трубопровод"] * 2 + ["Сварное соединение"] * 2 + ["Токарный станок"] * 2,
            ["Электродвигатель"] * 4 + ["Электрооборудование"] * 4 + ["КИПиА"] * 3 +
            ["Трубопровод"] * 2 + ["Насос", "Пневмосистема", "Охлаждающий контур"],
        ]
        for site_index, site in enumerate(self.data["sites"]):
            for ordinal, category in enumerate(categories[site_index], 1):
                count = len(self.data["equipment"]) + 1
                self.add("equipment", site_id=site["id"], name=f"{category} — учебный объект {count:02d}",
                         inventory_number=f"SYN-INV-{count:04d}", category=category,
                         model=f"Учебная модель U-{count:03d}",
                         criticality=self.random.choice(["medium", "high", "critical"]),
                         company_asset_confirmed=False)
        workers = [p for p in self.data["people"] if p["role"] == "worker"]
        for day_index in range((END - START).days + 1):
            day = START + timedelta(days=day_index)
            for phase, hour in enumerate([7, 15]):
                members = [p for p in workers
                           if ((int(p["username"].rsplit(".", 1)[-1]) - 1) // 5 + day_index) % 2 == phase]
                starts = datetime.combine(day, time(hour), TZ)
                shift = self.add("shifts", site_id=None, date=day.isoformat(),
                                 shift_code="day" if phase == 0 else "late",
                                 starts_at=stamp(starts), ends_at=stamp(starts + timedelta(hours=8)),
                                 worker_ids=[p["id"] for p in members],
                                 master_id=self.person_by_username[f"master.0{phase + 1}"]["id"],
                                 scope="shared_synthetic_training_shift")
                for person in members:
                    self.shift_by_person_day[(person["id"], day)] = shift

    def expected_material(self, code, quantity):
        material = self.material_by_code[code]
        return {"material_id": material["id"], "quantity": quantity,
                "unit": material["unit"], "tolerance_ratio": 0.25}

    def choose_scenario(self, equipment, forced=None):
        possibilities = [s for s in SCENARIOS if s["category"] == equipment["category"]]
        return next(s for s in possibilities if s["key"] == forced) if forced else self.random.choice(possibilities)

    def time_plan(self, day, scenario, equipment, issue, allow_delay=True):
        eligible = [p for p in self.data["people"] if p["role"] == "worker"
                    and set(p["skill_codes"]).intersection(scenario["skills"])]
        # A declared fictional teaching pattern: one fitter has more incomplete reports.
        eligible.sort(key=lambda p: (p["username"] != "worker.04", self.random.random()))
        if self.random.random() > 0.4:
            self.random.shuffle(eligible)
        candidates = []
        for person in eligible:
            shift = self.shift_by_person_day[(person["id"], day)]
            shift_start = datetime.fromisoformat(shift["starts_at"])
            shift_end = datetime.fromisoformat(shift["ends_at"])
            issued = max(shift_start + timedelta(minutes=self.random.randint(5, 35)),
                         self.worker_busy_until.get(person["id"], shift_start) + timedelta(minutes=2),
                         self.equipment_busy_until.get(equipment["id"], shift_start) + timedelta(minutes=2))
            if issued.date() != day:
                continue
            reaction = self.random.randint(1, 3)
            if issue == "slow_acceptance":
                reaction = self.random.randint(15, 25)
            accepted = issued + timedelta(minutes=reaction)
            wait = self.random.randint(1, 4)
            pause = 0
            # Late shifts deliberately have a higher *observed* waiting/downtime rate.
            shift_delayed = allow_delay and shift["shift_code"] == "late" and self.random.random() < 0.42
            if shift_delayed:
                wait += self.random.randint(65, 95)
                pause = self.random.randint(35, 60)
            if issue == "shift_delay" and allow_delay:
                wait += 65
                shift_delayed = True
            started = accepted + timedelta(minutes=wait)
            duration = round(scenario["minutes"] * self.random.uniform(0.82, 1.12)) if allow_delay else round(scenario["minutes"] * 0.82)
            if issue == "very_short_duration":
                duration = max(8, round(scenario["minutes"] * 0.28))
            if issue == "long_duration" and allow_delay:
                duration = round(scenario["minutes"] * 1.9)
            finished = started + timedelta(minutes=duration + pause)
            if finished + timedelta(minutes=6) <= shift_end:
                candidates.append((person, shift, issued, accepted, started, finished,
                                   pause, shift_delayed))
        if not candidates:
            if allow_delay:
                return self.time_plan(day, scenario, equipment, issue, allow_delay=False)
            raise RuntimeError(f"No feasible synthetic schedule for {day}: {equipment['name']}")
        # Prefer a feasible late shift for the waiting pattern, otherwise earliest finish.
        candidates.sort(key=lambda item: (item[0]["username"] != "worker.04", item[5]))
        if self.random.random() > 0.45:
            candidates.sort(key=lambda item: item[5])
        return candidates[0]

    def issue_object(self, code, fields):
        severity, explanation = ISSUE_DEFINITIONS[code]
        return {"code": code, "severity": severity, "explanation": explanation,
                "evidence_fields": fields}

    def add_order(self, index, day, equipment, scenario):
        # IDs never encode these classes. Outcomes follow actual synthetic fields.
        issue_pool = [None] * 13 + ["overdue"] * 3 + ["slow_acceptance", "very_short_duration",
                      "long_duration", "missing_after_photo", "empty_report", "work_mismatch",
                      "wrong_material", "excess_material", "missing_fault_code", "fault_code_mismatch"]
        selected_issue = self.random.choice(issue_pool)
        plan = self.time_plan(day, scenario, equipment, selected_issue)
        person, shift, issued, accepted, started, finished, pause, shift_delayed = plan
        if person["username"] == "worker.04" and self.random.random() < 0.78:
            selected_issue = self.random.choice(["empty_report", "work_mismatch", "wrong_material",
                                                "excess_material", "missing_fault_code"])
        kind = "planned" if scenario["planned"] else "unplanned"
        if selected_issue == "missing_after_photo" and kind == "planned":
            selected_issue = "empty_report"
        priority = "planned" if kind == "planned" else self.random.choice(["normal", "high", "emergency"])
        due = issued + timedelta(minutes=round(scenario["minutes"] * 1.45) + 12)
        if selected_issue == "overdue":
            due = max(issued + timedelta(minutes=5),
                      finished - timedelta(minutes=self.random.randint(15, 35)))
        expected = [dict(x) for x in self.norm_by_key[scenario["key"]]["expected_materials"]]
        # Vary fictional compatible parts within catalog families, never as engineering advice.
        for specification in expected:
            current = next(m for m in self.data["materials"] if m["id"] == specification["material_id"])
            code = current["code"]
            family = None
            if code.startswith("REF-BRG-"):
                family = "REF-BRG-"
            elif code.startswith("REF-GEAR-"):
                family = "REF-GEAR-"
            elif code.startswith("REF-HYD-"):
                family = "REF-HYD-"
            elif code.startswith("REF-WELD-"):
                family = "REF-WELD-"
            if family:
                variant = self.random.choice([m for m in self.data["materials"] if m["code"].startswith(family)])
                specification["material_id"] = variant["id"]
        title = scenario["title"]
        asset = equipment["inventory_number"]
        problem = self.random.choice(scenario["problem_variants"]).format(asset=asset)
        problem += self.random.choice([
            " Результат передать мастеру смены.", " Наблюдения и ограничения проверки записать в отчёт.",
            " Отразить фактический расход материалов.", " Допуски и порядок работ определяет утверждённая документация.",
        ])
        order = self.add("work_orders", number=f"SYN-2026-{index + 1:04d}", site_id=equipment["site_id"],
                         equipment_id=equipment["id"], assignee_id=person["id"],
                         brigade_id=person["brigade_id"], master_id=shift["master_id"], shift_id=shift["id"],
                         work_norm_id=self.norm_by_key[scenario["key"]]["id"], kind=kind,
                         priority=priority, title=title, problem_description=problem,
                         required_actions=list(scenario["actions"]), expected_materials=expected,
                         fault_code=scenario["fault_code"], issued_at=stamp(issued), accepted_at=stamp(accepted),
                         started_at=stamp(started), due_at=stamp(due), reported_at=stamp(finished),
                         closed_at=None, status="under_review")
        performed = self.random.choice(scenario["report_variants"]).format(asset=asset)
        performed += self.random.choice([
            " Запись передана мастеру для проверки.", " Ограничения осмотра отмечены в журнале.",
            " Использованные материалы отражены отдельно.", " Результат относится только к указанному учебному объекту.",
        ])
        if selected_issue == "empty_report":
            performed = self.random.choice(["Готово.", "Сделано, всё нормально.", "Работу закончил.", "Проверил, ок."])
        if selected_issue == "work_mismatch":
            performed = self.random.choice([
                "Проведена инвентаризация рабочего шкафа; пересчитаны канцелярские принадлежности.",
                "Обновлён график доставки воды, сверены подписи в журнале выдачи.",
                "Проверены таблички на складе хозяйственного инвентаря; замечания записаны.",
            ])
        fault = scenario["fault_code"]
        if selected_issue == "missing_fault_code":
            fault = None
        if selected_issue == "fault_code_mismatch":
            fault = "APP-19" if fault != "APP-19" else "APP-18"
        report = self.add("reports", work_order_id=order["id"], author_id=person["id"],
                          submitted_at=stamp(finished), performed_work=performed, fault_code=fault,
                          comment=("Ожидание учебной поставки и согласованного окна отражено в журнале."
                                   if shift_delayed else "Результат требует проверки мастером; данные учебные."))
        usage = []
        for specification in expected:
            quantity = specification["quantity"]
            if selected_issue == "excess_material":
                quantity = round(quantity * self.random.choice([4, 5, 6]), 3)
            usage.append(self.add("material_usage", work_order_id=order["id"], report_id=report["id"],
                                  material_id=specification["material_id"], quantity=quantity,
                                  unit=specification["unit"]))
        if selected_issue == "excess_material" and not expected:
            selected_issue = "wrong_material"
        if selected_issue == "wrong_material":
            # Choose a real catalog family outside the expected teaching bill of materials.
            expected_ids = {x["material_id"] for x in expected}
            extra = next(m for m in self.data["materials"] if m["id"] not in expected_ids
                         and m["code"].startswith("REF-WELD-"))
            if scenario["category"] == "Сварное соединение":
                extra = self.material_by_code["TRAIN-SENSOR"]
            usage.append(self.add("material_usage", work_order_id=order["id"], report_id=report["id"],
                                  material_id=extra["id"], quantity=2, unit=extra["unit"]))
        if self.random.random() < 0.44:
            self.add_photo(order, None, "before", issued, shift["master_id"], equipment)
        if selected_issue != "missing_after_photo" and (kind == "unplanned" or self.random.random() < 0.45):
            self.add_photo(order, report, "after", finished - timedelta(minutes=1), person["id"], equipment)
        issues = []
        if selected_issue in ["missing_after_photo", "empty_report", "work_mismatch", "wrong_material",
                              "excess_material", "missing_fault_code", "fault_code_mismatch"]:
            field = {"missing_after_photo": "photo_evidence.phase", "empty_report": "reports.performed_work",
                     "work_mismatch": "reports.performed_work", "wrong_material": "material_usage.material_id",
                     "excess_material": "material_usage.quantity", "missing_fault_code": "reports.fault_code",
                     "fault_code_mismatch": "reports.fault_code"}[selected_issue]
            issues.append(self.issue_object(selected_issue, [field]))
        if finished > due:
            issues.append(self.issue_object("overdue", ["work_orders.due_at", "reports.submitted_at"]))
        reaction = (accepted - issued).total_seconds() / 60
        threshold = 3 if priority == "emergency" else 10
        if reaction > threshold:
            issues.append(self.issue_object("slow_acceptance", ["work_orders.issued_at", "work_orders.accepted_at"]))
        duration = (finished - started).total_seconds() / 60
        if duration < scenario["minutes"] * 0.4:
            issues.append(self.issue_object("very_short_duration", ["work_orders.started_at", "reports.submitted_at", "work_norms.expected_minutes"]))
        if duration > scenario["minutes"] * 1.5:
            issues.append(self.issue_object("long_duration", ["work_orders.started_at", "reports.submitted_at", "work_norms.expected_minutes"]))
        if (started - accepted).total_seconds() / 60 > 45:
            issues.append(self.issue_object("shift_delay", ["work_orders.accepted_at", "work_orders.started_at"]))
        severe = any(x["severity"] == "rework" for x in issues)
        verdict = "rework_required" if severe else "accepted_with_remarks" if issues else "accepted"
        score = max(15, 96 - sum(28 if x["severity"] == "rework" else 9 for x in issues))
        score = min(score, 60) if severe else score
        self.add("answer_keys", work_order_id=order["id"], report_id=report["id"], verdict=verdict,
                 score=score, issues=issues,
                 reasons=[x["explanation"] for x in issues] or ["Текстовая полнота, учебный расход и сроки соответствуют заданным правилам; фото не оценивалось."],
                 photo_verdict="not_assessed", manual_review_required=True,
                 master_decision_simulated=True, label_origin="deterministic_synthetic_rules",
                 analytics_flags=[])
        final = finished + timedelta(minutes=5)
        order["status"] = "rework_required" if severe else "closed"
        order["closed_at"] = None if severe else stamp(final)
        previous = None
        def event(action, target, occurred, actor, comment=""):
            nonlocal previous
            self.add("status_events", work_order_id=order["id"], actor_id=actor,
                     action=action, from_status=previous, to_status=target,
                     occurred_at=stamp(occurred), comment=comment)
            previous = target
        event("issue", "issued", issued, shift["master_id"])
        event("accept", "accepted", accepted, person["id"])
        if (started - accepted).total_seconds() > 300:
            event("queue", "queued", accepted + timedelta(minutes=1), person["id"],
                  "Ожидание учебного окна выполнения.")
        event("start", "in_progress", started, person["id"])
        if pause:
            active_minutes = int((finished - started).total_seconds() / 60) - pause
            pause_start = min(10, max(1, active_minutes // 2))
            event("pause", "paused", started + timedelta(minutes=pause_start), person["id"],
                  "Ожидание учебной поставки, событие синтетическое.")
            event("resume", "in_progress", started + timedelta(minutes=pause_start + pause), person["id"])
        event("submit_report", "completed", finished, person["id"])
        event("request_review", "under_review", finished + timedelta(minutes=1), shift["master_id"])
        event("simulated_master_review", order["status"], final, shift["master_id"],
              "Учебное решение по правилам; реальный мастер не участвовал.")
        # No production downtime is implied. Interval is exactly the synthetic unavailability window.
        if kind == "unplanned" or self.random.random() < 0.6:
            self.add("downtime_intervals", work_order_id=order["id"], equipment_id=equipment["id"],
                     started_at=stamp(issued), ended_at=stamp(finished), reason_code=scenario["fault_code"],
                     planned=kind == "planned", duration_minutes=round((finished - issued).total_seconds() / 60, 2))
        self.worker_busy_until[person["id"]] = final
        self.equipment_busy_until[equipment["id"]] = final

    def add_photo(self, order, report, phase, captured, author, equipment):
        self.add("photo_evidence", work_order_id=order["id"], report_id=report["id"] if report else None,
                 phase=phase, captured_at=stamp(captured), author_id=author,
                 equipment_id=equipment["id"], attachment_present=True,
                 content_origin="simulated_metadata_only", image_available=False,
                 photo_verdict="not_assessed", manual_review_required=True,
                 note="Смоделировано только наличие вложения. Изображения и доказательства ремонта отсутствуют.")

    def build_orders(self, count):
        equipment = self.data["equipment"]
        hot_conveyor = next(e for e in equipment if e["category"] == "Конвейер")
        hot_pump = next(e for e in equipment if e["category"] == "Насос")
        ordinary = [e for e in equipment if e["id"] != hot_conveyor["id"]]
        cursor = 0
        day_counts = Counter()
        for index in range(count):
            day_index = index * ((END - START).days + 1) // count
            day = START + timedelta(days=day_index)
            position = day_counts[day]
            day_counts[day] += 1
            if day_index % 2 == 0 and position == 0:
                asset, forced = hot_conveyor, "conveyor_bearing"
            elif day_index % 4 == 1 and position == 0:
                asset, forced = hot_pump, "pump_leak"
            else:
                # Coprime stride distributes specialties across days instead of
                # assigning five adjacent cars to the sole automotive fitter.
                asset, forced = ordinary[(cursor * 17) % len(ordinary)], None
                cursor += 1
            self.add_order(index, day, asset, self.choose_scenario(asset, forced))
        self.add_history_answer_keys(hot_conveyor)

    def add_history_answer_keys(self, hot_conveyor):
        orders = self.data["work_orders"]
        keys = {x["work_order_id"]: x for x in self.data["answer_keys"]}
        by_asset = defaultdict(list)
        for order in sorted(orders, key=lambda x: x["issued_at"]):
            history = by_asset[order["equipment_id"]]
            issued = datetime.fromisoformat(order["issued_at"])
            recent = [old for old in history if timedelta(0) < issued - datetime.fromisoformat(old["reported_at"]) <= timedelta(days=14)]
            flags = []
            if order["kind"] == "unplanned":
                repeated = [old for old in recent if old["kind"] == "unplanned" and old["fault_code"] == order["fault_code"]]
                if repeated:
                    flags.append({"code": "repeated_failure", "related_work_order_ids": [old["id"] for old in repeated],
                                  "lookback_days": 14, "explanation": ISSUE_DEFINITIONS["repeated_failure"][1]})
                planned = [old for old in recent if old["kind"] == "planned"
                           and issued - datetime.fromisoformat(old["reported_at"]) <= timedelta(days=7)]
                if planned:
                    flags.append({"code": "failure_after_planned", "related_work_order_ids": [old["id"] for old in planned],
                                  "lookback_days": 7, "explanation": ISSUE_DEFINITIONS["failure_after_planned"][1]})
            keys[order["id"]]["analytics_flags"] = flags
            history.append(order)
        counts = Counter(o["equipment_id"] for o in orders if o["kind"] == "unplanned")
        conveyor_ids = [e["id"] for e in self.data["equipment"] if e["category"] == "Конвейер" and e["id"] != hot_conveyor["id"]]
        baseline = sum(counts[x] for x in conveyor_ids) / len(conveyor_ids)
        per_worker = defaultdict(lambda: [0, 0])
        for order in orders:
            per_worker[order["assignee_id"]][0] += 1
            per_worker[order["assignee_id"]][1] += keys[order["id"]]["verdict"] == "rework_required"
        target = self.person_by_username["worker.04"]["id"]
        others_n = sum(values[0] for person, values in per_worker.items() if person != target)
        others_bad = sum(values[1] for person, values in per_worker.items() if person != target)
        shifts = {s["id"]: s for s in self.data["shifts"]}
        order_map = {o["id"]: o for o in orders}
        by_shift = defaultdict(list)
        for interval in self.data["downtime_intervals"]:
            order = order_map[interval["work_order_id"]]
            by_shift[shifts[order["shift_id"]]["shift_code"]].append(interval["duration_minutes"])
            if interval["duration_minutes"] > 150:
                keys[order["id"]]["analytics_flags"].append({"code": "long_downtime",
                    "duration_minutes": interval["duration_minutes"], "threshold_minutes": 150,
                    "explanation": ISSUE_DEFINITIONS["long_downtime"][1]})
        self.patterns = [
            {"code": "frequent_conveyor_failure", "equipment_id": hot_conveyor["id"],
             "unplanned_count": counts[hot_conveyor["id"]], "peer_equipment_ids": conveyor_ids,
             "peer_mean_unplanned_count": round(baseline, 4),
             "ratio_to_peer_mean": round(counts[hot_conveyor["id"]] / baseline, 4) if baseline else None,
             "calculated_from": "work_orders.kind,equipment.category", "causality_established": False},
            {"code": "worker_rework_rate", "person_id": target, "orders_count": per_worker[target][0],
             "rework_count": per_worker[target][1],
             "rework_rate": round(per_worker[target][1] / per_worker[target][0], 4),
             "others_rework_rate": round(others_bad / others_n, 4),
             "calculated_from": "work_orders.assignee_id,answer_keys.verdict", "causality_established": False},
            {"code": "repeat_fault_within_14_days", "equipment_id": hot_conveyor["id"],
             "flagged_orders_count": sum(any(f["code"] == "repeated_failure" for f in keys[o["id"]]["analytics_flags"])
                                         for o in orders if o["equipment_id"] == hot_conveyor["id"]),
             "lookback_days": 14, "calculated_from": "work_orders.equipment_id,fault_code,issued_at,reported_at",
             "causality_established": False},
            {"code": "shift_downtime_difference",
             "by_shift": {code: {"interval_count": len(values),
                                  "mean_minutes": round(sum(values) / len(values), 4),
                                  "long_intervals_count": sum(v > 150 for v in values)}
                          for code, values in sorted(by_shift.items())},
             "calculated_from": "downtime_intervals.duration_minutes,shifts.shift_code",
             "causality_established": False},
        ]

    def result(self):
        metadata = syn(dataset_id="naryadai-synthetic-training-20261008", schema_version=1,
                       seed=self.seed, generated_at="2026-10-08T00:00:00+05:00",
                       period={"starts_at": "2026-07-08T00:00:00+05:00", "ends_at": "2026-10-07T23:59:59+05:00"},
                       intended_use="Synthetic text checking, deadline analytics and reproducible software evaluation.",
                       source_catalog="database/production/reference_catalog.json",
                       source_catalog_sha256=hashlib.sha256(json.dumps(self.catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                       fault_codes=self.catalog["defect_codes"], counts={name: len(self.data[name]) for name in COLLECTIONS},
                       verdict_distribution=dict(Counter(k["verdict"] for k in self.data["answer_keys"])),
                       analytics_patterns=self.patterns,
                       limitations=["Все наряды, события, квалификации, инвентарные объекты и нормы вымышлены.",
                           "ФИО вымышлены. Логины используются только как учебные идентификаторы; паролей нет.",
                           "26 материалов — ссылки на публичные каталоги; 14 позиций вымышлены для кейса. Фактические остатки и цены отсутствуют.",
                           "Совместимость материалов, количества и сроки — учебные допущения без инженерного согласования.",
                           "Изображений нет. Записи photo_evidence имитируют наличие вложений и не доказывают качество ремонта.",
                           "Метки построены правилами генератора; это не экспертная разметка и не оценка настоящих сотрудников.",
                           "Результаты ИИ рекомендательные, финальное решение принимает реальный мастер.",
                           "Набор не подключается к рабочей БД и не пригоден для инструктажа по ремонту."])
        return {"metadata": metadata, **self.data}


def build_dataset(catalog_path: Path | None = None, seed: int = SEED, count: int = 500):
    if count < 500:
        raise ValueError("Case 1 requires at least 500 work orders")
    catalog_path = catalog_path or Path(__file__).resolve().parents[1] / "production" / "reference_catalog.json"
    builder = Builder(json.loads(catalog_path.read_text(encoding="utf-8")), seed)
    builder.build_references()
    builder.build_orders(count)
    return builder.result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New synthetic dataset JSON path; never the production DB")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    dataset = build_dataset(args.catalog, args.seed, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit("Output exists; choose a new path to preserve the previous dataset.")
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(dataset, stream, ensure_ascii=False, indent=2 if args.pretty else None,
                  separators=None if args.pretty else (",", ":"))
        stream.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "counts": dataset["metadata"]["counts"],
                      "verdicts": dataset["metadata"]["verdict_distribution"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
