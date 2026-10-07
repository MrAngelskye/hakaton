#!/usr/bin/env python3
"""Build and validate a separate synthetic corpus using only Python's stdlib."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_dataset import SEED, build_dataset
from export_dataset import export
from validate_dataset import validate_dataset


def save_json(path: Path, payload: object, *, pretty: bool = True) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                               indent=2 if pretty else None,
                               separators=None if pretty else (",", ":")) + "\n", encoding="utf-8")


def write_archive(output: Path, archive: Path) -> None:
    """Fixed paths, timestamps and permissions; never overwrite an archive."""
    paths = sorted(p for p in output.rglob("*") if p.is_file())
    if archive.name.endswith(".tar.xz"):
        with tarfile.open(archive, "x:xz", format=tarfile.PAX_FORMAT, preset=6) as packed:
            for path in paths:
                content = path.read_bytes()
                entry = tarfile.TarInfo(path.relative_to(output).as_posix())
                entry.size, entry.mode, entry.mtime = len(content), 0o644, 0
                packed.addfile(entry, io.BytesIO(content))
    elif archive.suffix == ".zip":
        with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as zipped:
            for path in paths:
                entry = ZipInfo(path.relative_to(output).as_posix(), date_time=(2026, 10, 8, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                zipped.writestr(entry, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    else:
        raise ValueError("Supported archive extensions: .tar.xz or .zip")


def prepare(output: Path, archive: Path | None, seed: int = SEED) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a NEW output directory; existing files are never overwritten")
    if archive:
        archive = archive.resolve()
        if not (archive.name.endswith(".tar.xz") or archive.suffix == ".zip"):
            raise ValueError("Supported archive extensions: .tar.xz or .zip")
        if archive.exists() or output == archive or output in archive.parents:
            raise ValueError("Archive must be a new path outside the output directory")
    data = build_dataset(seed=seed)
    report = validate_dataset(data)
    if not report["valid"]:
        raise ValueError(json.dumps(report["errors"], ensure_ascii=False))
    output.mkdir(parents=True)
    dataset_path = output / "dataset.json"
    save_json(dataset_path, data, pretty=False)
    exports = output / "exports"
    export_report = export(dataset_path, exports)
    validation = validate_dataset(data, exports)
    save_json(output / "validation_report.json", validation)
    if not validation["valid"]:
        raise ValueError(json.dumps(validation["errors"], ensure_ascii=False))
    catalog = Path(__file__).resolve().parents[1] / "production" / "reference_catalog.json"
    (output / "reference_catalog.json").write_bytes(catalog.read_bytes())
    (output / "analytics.sql").write_bytes(Path(__file__).with_name("analytics.sql").read_bytes())
    (output / "README.txt").write_text(
        "НарядAI: СИНТЕТИЧЕСКИЙ учебный набор, кейс №1.\n"
        "Все люди, наряды, события, инвентарные объекты и нормы вымышлены.\n"
        "Паролей и настоящих фотографий ремонта здесь нет. Модель не обучена.\n\n"
        "dataset.json — связанные исходные записи и отдельные ключи ответов.\n"
        "exports/ai_training.sqlite3 — готовая отдельная SQLite для просмотра.\n"
        "exports/postgresql.sql — импорт в отдельную схему naryadai_ai_training.\n"
        "exports/csv — таблицы; exports/train.jsonl, validation.jsonl, test.jsonl — примеры для ИИ.\n"
        "exports/rag — история оборудования без ответов; соблюдайте разделение и available_at.\n"
        "answer_keys служат только учебными ответами, не входом модели.\n"
        "Изображения отсутствуют: photo_evidence содержит только имитацию метаданных.\n"
        "Не импортируйте эту схему в рабочие таблицы приложения.\n\n"
        "Код, инструкции и ограничения:\n"
        "https://github.com/MrAngelskye/hakaton/tree/codex/ai-training-dataset/database/ai_training\n",
        encoding="utf-8")
    source = Path(__file__).resolve().parent
    manifest = {
        "dataset_id": data["metadata"]["dataset_id"], "synthetic": True,
        "seed": seed, "period": data["metadata"]["period"],
        "counts": data["metadata"]["counts"],
        "verdict_distribution": data["metadata"]["verdict_distribution"],
        "jsonl_counts": export_report["jsonl_counts"],
        "postgresql_schema": export_report["postgresql_schema"],
        "source_code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(source.glob("*.py"))},
        "source_catalog_sha256": data["metadata"]["source_catalog_sha256"],
        "files": {p.relative_to(output).as_posix(): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in sorted(output.rglob("*")) if p.is_file()},
    }
    save_json(output / "manifest.json", manifest)
    result = {"output": str(output), "counts": manifest["counts"],
              "jsonl_counts": manifest["jsonl_counts"], "valid": True}
    if archive:
        archive.parent.mkdir(parents=True, exist_ok=True)
        write_archive(output, archive)
        result["archive"] = str(archive)
        result["archive_bytes"] = archive.stat().st_size
        result["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputdir", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    print(json.dumps(prepare(args.outputdir, args.archive, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
