"""Deterministic report checks; no Qt, network or decisions about repair quality.

Call inspect_submission after authorisation, before copying photos. Persist the
returned list as reports.checks. Duplicate evidence is only for master/admin;
visible_checks must be applied when exposing reports to workers.
"""
import hashlib
import io
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

LOCAL_TIMEZONE = timezone(timedelta(hours=5))  # Asia/Qyzylorda, current UTC+5.
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
POLICY = {'max_age_hours': 72, 'clock_tolerance_minutes': 10,
          'before_task_tolerance_minutes': 5, 'similarity_distance': 2,
          'legacy_photo_reads': 24}


def _check(identifier, field, severity, message, photo_index=None, **extra):
    result = {'id': identifier, 'field': field, 'severity': severity, 'message': message}
    if photo_index is not None:
        result['photo_index'] = photo_index
    result.update(extra)
    return result


def _date(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    return result.replace(tzinfo=LOCAL_TIMEZONE) if result.tzinfo is None else result


def _capture(exif):
    """Only original/digitised capture dates, not filesystem mtime/EXIF modified date."""
    data = dict(exif)
    try:
        data.update(exif.get_ifd(34665))
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        pass
    for date_tag, offset_tag in ((36867, 36881), (36868, 36882)):
        raw = data.get(date_tag)
        if not isinstance(raw, str):
            continue
        try:
            captured = datetime.strptime(raw.rstrip('\x00'), '%Y:%m:%d %H:%M:%S')
        except ValueError:
            continue
        offset = data.get(offset_tag)
        if isinstance(offset, str):
            try:
                captured = datetime.fromisoformat(captured.isoformat() + offset.rstrip('\x00'))
                return captured, False
            except ValueError:
                pass
        return captured.replace(tzinfo=LOCAL_TIMEZONE), True
    return None, False


def fingerprint(raw):
    """Validate bytes, calculate SHA256/dHash and original capture metadata."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError('Фото: JPG, PNG или WebP до 8 МБ.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > MAX_PIXELS:
                raise ValueError('Фото: JPG, PNG или WebP до 40 Мп.')
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            captured, assumed = _capture(image.getexif())
            image.load()
            size = image.size
            oriented = ImageOps.exif_transpose(image).convert('RGB')
            thumb = oriented.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
            values = list(thumb.tobytes())
            bits = 0
            for y in range(8):
                for x in range(8):
                    bits = (bits << 1) | (values[y * 9 + x] > values[y * 9 + x + 1])
            spread = ImageStat.Stat(oriented.convert('L').resize((32, 32))).stddev[0]
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError('Файл не является поддерживаемой фотографией (до 8 МБ и 40 Мп).') from error
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'dhash': f'{bits:016x}',
            'width': size[0], 'height': size[1], 'visual_spread': round(spread, 2),
            'captured_at': captured.isoformat(timespec='seconds') if captured else None,
            'capture_timezone_assumed': assumed}


def visible_checks(checks, role):
    """Copy safe messages; report IDs and evidence remain private to reviewers."""
    result = []
    for check in checks or []:
        item = dict(check)
        if role not in ('master', 'admin'):
            item.pop('evidence', None)
            item.pop('source_report_id', None)
        result.append(item)
    return result


def _decode(value, fallback):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value if value is not None else fallback


def _previous(c, store, task_id, max_legacy_reads):
    """Use persisted fingerprints; legacy reports are read once per inspection."""
    rows = c.execute('SELECT * FROM reports WHERE task_id<>? ORDER BY id DESC', (task_id,)).fetchall()
    legacy_reads = 0
    for row in rows:
        report = dict(row)
        names = _decode(report.get('photos'), [])
        checks = _decode(report.get('checks'), [])
        known = {p.get('photo_index'): p.get('metadata') for p in checks
                 if isinstance(p, dict) and p.get('id') == 'photo_metadata' and isinstance(p.get('metadata'), dict)}
        for index, name in enumerate(names):
            metadata = known.get(index)
            if not metadata:
                if legacy_reads >= max_legacy_reads:
                    yield None, None, None
                    continue
                try:
                    # Only basenames recorded by the store; never accept a path from a report.
                    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
                        continue
                    legacy_reads += 1
                    raw = store.read_photo(name) if hasattr(store, 'read_photo') else (Path(store.photos) / name).read_bytes()
                    metadata = fingerprint(raw)
                except (OSError, ValueError):
                    continue
            yield report['id'], index, metadata


def _similar(first, second, distance):
    # Flat/tiny images have uninformative hashes. Exact SHA256 still detects them.
    if min(first.get('width', 0), first.get('height', 0), second.get('width', 0), second.get('height', 0)) < 32:
        return False
    if min(first.get('visual_spread', 0), second.get('visual_spread', 0)) < 12:
        return False
    try:
        return (int(first['dhash'], 16) ^ int(second['dhash'], 16)).bit_count() <= distance
    except (KeyError, TypeError, ValueError):
        return False


def inspect_submission(c, store, task_id, sources, at=None):
    """Returns serialisable checks with severity info/warn/block, without writes.

    Missing EXIF is information, not proof of an old photo. Timestamp/duplicate
    warnings require a master's assessment; only invalid images block submission.
    at is the server upload time, never filesystem modification time.
    """
    at = _date(at) or datetime.now(LOCAL_TIMEZONE)
    settings = dict(POLICY)
    settings.update(getattr(store, 'photo_check_policy', {}) or {})
    row = c.execute('SELECT created FROM tasks WHERE id=?', (task_id,)).fetchone()
    created = _date(row['created']) if row else None
    checks = []
    current = []
    for index, source in enumerate(sources):
        try:
            path = Path(source)
            if not path.is_file() or path.stat().st_size > MAX_BYTES or path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
                raise ValueError('Фото: JPG, PNG или WebP до 8 МБ.')
            metadata = fingerprint(path.read_bytes())
        except (OSError, TypeError, ValueError) as error:
            message = str(error) if isinstance(error, ValueError) else 'Фото недоступно или не является поддерживаемым изображением.'
            checks.append(_check('invalid_image', 'photos', 'block', message, index))
            continue
        metadata['uploaded_at'] = at.isoformat(timespec='seconds')
        checks.append(_check('photo_metadata', 'photos', 'info', 'Фото прочитано; время загрузки сохранено отдельно от времени съёмки.', index, metadata=metadata))
        captured = _date(metadata['captured_at'])
        if not captured:
            checks.append(_check('capture_time_missing', 'photos', 'info', 'В фото нет исходной даты съёмки EXIF. Это не доказывает, что фото старое; время загрузки известно.', index))
        else:
            if captured > at + timedelta(minutes=settings['clock_tolerance_minutes']):
                checks.append(_check('capture_in_future', 'photos', 'warn', 'Дата съёмки позже времени загрузки. Мастеру нужно уточнить часы камеры и происхождение фото.', index))
            elif created and captured < created - timedelta(minutes=settings['before_task_tolerance_minutes']):
                checks.append(_check('capture_before_task', 'photos', 'warn', 'По EXIF фото снято до создания наряда. Уточните, относится ли оно к текущей работе; EXIF может быть изменён.', index))
            elif settings.get('max_age_hours') is not None and at - captured > timedelta(hours=settings['max_age_hours']):
                checks.append(_check('capture_too_old', 'photos', 'warn', 'Дата съёмки выходит за настроенный срок актуальности. Мастеру нужно проверить связь фото с текущей работой.', index))
        for previous_index, previous in current:
            if previous['sha256'] == metadata['sha256']:
                checks.append(_check('photo_repeated_in_submission', 'photos', 'warn', 'Одна и та же фотография приложена несколько раз. Замените повтор на другой ракурс, если он нужен.', index))
                break
        current.append((index, metadata))
    if current:
        # One warning per photo. Exact matches take precedence over perceptual matches.
        # Cloud legacy reads would perform network downloads inside a transaction.
        # New indexed reports always participate; backfill legacy photos separately.
        max_reads = 0 if hasattr(store, 'storage') else settings['legacy_photo_reads']
        history = list(_previous(c, store, task_id, max_reads))
        previous = [r for r in history if r[2] is not None]
        if len(previous) != len(history):
            checks.append(_check('legacy_history_partial', 'photos', 'info',
                'Часть старых фото ещё не имеет индекса. Проверка повторов охватывает проиндексированные снимки; отсутствие совпадения не доказывает уникальность.'))
        for index, metadata in current:
            exact = next((r for r in previous if r[2].get('sha256') == metadata['sha256']), None)
            near = exact or next((r for r in previous if _similar(metadata, r[2], settings['similarity_distance'])), None)
            if near:
                checks.append(_check('photo_reused' if exact else 'photo_similar', 'photos', 'warn',
                    'Такая фотография уже встречалась в другом наряде. Мастер проверит контекст; повтор не означает нарушение.' if exact else
                    'Фото визуально похоже на снимок из другого наряда. Совпадение приблизительное и требует проверки мастером.',
                    index, evidence={'source_report_id': near[0], 'source_photo_index': near[1]}))
    return checks


def inspect_report_fields(*, work='', result='', hours=None, materials=None):
    """Field-specific input checks for forms; empty materials is a valid no-use case."""
    checks = []
    if not isinstance(work, str) or len(work.strip()) < 10:
        checks.append(_check('work_missing', 'work', 'block', 'Опишите выполненные действия: от 10 символов.'))
    if not isinstance(result, str) or len(result.strip()) < 3:
        checks.append(_check('result_missing', 'result', 'block', 'Укажите результат контрольной проверки: от 3 символов.'))
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not math.isfinite(hours) or not .1 <= hours <= 24:
        checks.append(_check('time_invalid', 'hours', 'block', 'Укажите фактическое время от 0,1 до 24 часов.'))
    if not isinstance(materials, list):
        checks.append(_check('materials_invalid', 'materials', 'block', 'Передайте список использованных материалов; пустой список допустим.'))
    else:
        for index, material in enumerate(materials):
            try:
                valid = (isinstance(material['name'], str) and material['name'].strip() and
                         isinstance(material['unit'], str) and material['unit'].strip() and
                         math.isfinite(float(material['quantity'])) and float(material['quantity']) > 0 and
                         math.isfinite(float(material.get('price', 0))) and float(material.get('price', 0)) >= 0)
            except (TypeError, ValueError, KeyError):
                valid = False
            if not valid:
                checks.append(_check('material_invalid', 'materials', 'block', f'Материал {index + 1}: заполните название, единицу и положительное количество; цена — от 0.'))
    return checks
