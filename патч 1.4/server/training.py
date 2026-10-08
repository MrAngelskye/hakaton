"""Explicit, bounded access to a separate synthetic corpus. No answer keys."""
import json
import re
from datetime import date, datetime


def requested(message):
    return bool(re.search(r'учебн|синтетичес|training\s+(?:data|set)|synthetic|\bSYN-', message, re.I))


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def retrieve(c, message, tokens):
    if not c.execute("SELECT to_regclass('naryadai_ai_training.work_orders') AS relation").fetchone()['relation']:
        return {'available': False, 'synthetic': True, 'note': 'Учебный набор ещё не загружен.'}
    info = c.execute('''SELECT
        (SELECT count(*) FROM naryadai_ai_training.work_orders) AS orders,
        (SELECT count(*) FROM naryadai_ai_training.equipment) AS equipment,
        (SELECT count(*) FROM naryadai_ai_training.materials) AS materials''').fetchone()
    period = c.execute("SELECT value FROM naryadai_ai_training.dataset_metadata WHERE key='period'").fetchone()
    conditions, args = [], []
    number = re.search(r'\bSYN-2026-\d{4}\b', message, re.I)
    inventory = re.search(r'\bSYN-INV-\d{4}\b', message, re.I)
    if number:
        conditions.append('w.number=?');args.append(number[0].upper())
    elif inventory:
        conditions.append('e.inventory_number=?');args.append(inventory[0].upper())
    else:
        stop = {'учебн','синте','приме','набор','анали','разбе','истор','датас'}
        for token in sorted(tokens - stop)[:4]:
            conditions.append('(w.title ILIKE ? OR w.problem_description ILIKE ? OR e.name ILIKE ?)')
            args.extend(['%'+token+'%']*3)
    where = ' WHERE '+' OR '.join(conditions) if conditions else ''
    rows = c.execute('''SELECT w.number,w.title,w.problem_description,w.required_actions,
        w.expected_materials,w.fault_code,w.issued_at,w.due_at,
        e.inventory_number,e.name AS equipment_name,r.performed_work,r.comment
        FROM naryadai_ai_training.work_orders w
        JOIN naryadai_ai_training.equipment e ON e.id=w.equipment_id
        LEFT JOIN naryadai_ai_training.reports r ON r.work_order_id=w.id'''
        +where+' ORDER BY w.number LIMIT 3', tuple(args)).fetchall()
    examples = []
    for row in rows:
        record = dict(row)
        for key in ('required_actions','expected_materials'):
            record[key] = _json(record[key])
        for key, value in record.items():
            if isinstance(value, str):record[key]=value[:600]
            elif isinstance(value, (date,datetime)):record[key]=value.isoformat()
        examples.append(record)
    return {'available': True, 'synthetic': True, 'source_schema': 'naryadai_ai_training',
            'counts': dict(info), 'dataset_period': _json(period['value']) if period else None,
            'examples': examples, 'actual_images': False,
            'note': 'Всё здесь — вымышленные учебные примеры, не рабочие наряды и не история предприятия. '
                    'Фотографий нет. Оценки и решения мастера не переданы модели. '
                    'Не добавляй эти записи в рабочую статистику, рейтинг сотрудников или список нарядов.'}
