"""Adversarial checks against independently corrupted copies of the corpus."""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from validate_dataset import validate_dataset


class DatasetValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(__file__).resolve().parent
        dataset = Path(os.environ.get("NARYADAI_TRAINING_DATASET", cls.directory / "dataset.json"))
        cls.payload = json.loads(dataset.read_text(encoding="utf-8"))
        cls.exports = Path(os.environ.get("NARYADAI_TRAINING_EXPORTS", cls.directory / "exports"))

    def assert_invalid(self, data, fragment, exports=None):
        report = validate_dataset(data, exports)
        self.assertFalse(report["valid"])
        self.assertTrue(any(fragment in message for message in report["errors"]), report["errors"][:15])

    def copy_exports(self, directory):
        for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "split_manifest.json"):
            shutil.copyfile(self.exports / name, directory / name)

    def change_first_example(self, directory, mutate):
        path = directory / "train.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        example = json.loads(lines[0])
        user = json.loads(example["messages"][1]["content"])
        mutate(user, example)
        example["messages"][1]["content"] = json.dumps(user, ensure_ascii=False)
        lines[0] = json.dumps(example, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_intentional_business_discrepancies_are_valid_examples(self):
        report = validate_dataset(self.payload, self.exports)
        self.assertTrue(report["valid"], report["errors"][:20])
        self.assertGreaterEqual(len(report["statistics"]["issue_codes"]), 5)
        self.assertGreaterEqual(len(report["statistics"]["verdicts"]), 2)

    def test_broken_foreign_key_is_rejected(self):
        data = copy.deepcopy(self.payload)
        data["work_orders"][0]["equipment_id"] = "NONEXISTENT-EQUIPMENT"
        self.assert_invalid(data, "invalid equipment_id")

    def test_overlapping_active_orders_for_one_worker_are_rejected(self):
        data = copy.deepcopy(self.payload)
        first = data["work_orders"][0]
        second = next(order for order in data["work_orders"][1:] if order["assignee_id"] == first["assignee_id"])
        for field in ("issued_at", "accepted_at", "started_at", "due_at", "reported_at", "shift_id"):
            second[field] = first[field]
        second["closed_at"] = first["closed_at"] if second["status"] == "closed" else None
        self.assert_invalid(data, "overlapping active orders")

    def test_downtime_arithmetic_is_checked(self):
        data = copy.deepcopy(self.payload)
        data["downtime_intervals"][0]["duration_minutes"] += 17
        self.assert_invalid(data, "does not match timestamps")

    def test_invented_analytics_summary_is_rejected(self):
        data = copy.deepcopy(self.payload)
        pattern = next(item for item in data["metadata"]["analytics_patterns"] if item["code"] == "frequent_conveyor_failure")
        pattern["unplanned_count"] += 5
        self.assert_invalid(data, "differs from independent recalculation")

    def test_unjustified_acceptance_verdict_is_rejected(self):
        data = copy.deepcopy(self.payload)
        answer = next(item for item in data["answer_keys"] if item["verdict"] == "rework_required")
        answer["verdict"] = "accepted"
        self.assert_invalid(data, "verdict contradicts issue severity")

    def test_unjustified_default_score_is_rejected(self):
        data = copy.deepcopy(self.payload)
        answer = next(item for item in data["answer_keys"] if item["verdict"] == "rework_required")
        answer["score"] = 96
        self.assert_invalid(data, "rule score contradicts")

    def test_simulated_photo_cannot_be_claimed_as_real_image(self):
        data = copy.deepcopy(self.payload)
        data["photo_evidence"][0]["image_available"] = True
        data["photo_evidence"][0]["photo_verdict"] = "repair_verified"
        self.assert_invalid(data, "image quality must not be fabricated")

    def test_target_label_leak_into_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.copy_exports(directory)
            self.change_first_example(directory, lambda user, _: user["report"].update(verdict="accepted"))
            self.assert_invalid(self.payload, "ground truth leaks", directory)

    def test_worker_identity_leak_into_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.copy_exports(directory)
            self.change_first_example(directory, lambda user, _: user["report"].update(author_id=self.payload["people"][0]["id"]))
            self.assert_invalid(self.payload, "worker identity leaks", directory)

    def test_same_order_history_leak_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.copy_exports(directory)

            def mutate(user, _):
                user["history"] = [{"work_order": {"id": user["work_order"]["id"]}, "report": user["report"]}]

            self.change_first_example(directory, mutate)
            self.assert_invalid(self.payload, "future or same-order history leakage", directory)

    def test_equipment_overlap_between_splits_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.copy_exports(directory)
            path = directory / "split_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            equipment = manifest["partitions"]["train"]["equipment_ids"][0]
            manifest["partitions"]["test"]["equipment_ids"].append(equipment)
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            self.assert_invalid(self.payload, "equipment overlap between splits", directory)


if __name__ == "__main__":
    unittest.main()
