"""Правила MVP: справочники, назначения, уведомления и история оборудования.

Модуль не зависит от Qt. Демонстрационные справочники не являются данными заказчика.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    COMPANY_TZ = ZoneInfo('Asia/Qyzylorda')
except ZoneInfoNotFoundError:
    COMPANY_TZ = timezone(timedelta(hours=5), 'Asia/Qyzylorda')

PRIORITIES = {'urgent': 'Аварийный', 'high': 'Высокий', 'normal': 'Обычный', 'routine': 'Плановый'}
REFERENCE_CATEGORIES = ('sites', 'equipment', 'brigades', 'defects', 'materials', 'normatives')
DEFAULT_NOTIFICATIONS = {'reminder_minutes': 30, 'accept_minutes': 10, 'urgent_accept_minutes': 3}
OPEN_TASK_STATUSES = ('available', 'issued', 'accepted', 'queued', 'planned', 'inProgress', 'paused', 'revision')


def company_time(value=None):
    if value is None:
        return datetime.now(COMPANY_TZ)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=COMPANY_TZ) if value.tzinfo is None else value.astimezone(COMPANY_TZ)


def local_stamp():
    # Existing SQLite dates are wall-clock timestamps. Preserve their representation.
    return company_time().replace(tzinfo=None).isoformat(timespec='seconds')


class WorkflowMixin:
    def migrate_workflow(self):
        with self.transaction() as c:
            additions = {
                'tasks': {'issued_at': 'TEXT', 'accepted_at': 'TEXT', 'actual_started': 'TEXT',
                          'completed_at': 'TEXT', 'rejected_reason': "TEXT NOT NULL DEFAULT ''",
                          'brigade_id': 'INTEGER', 'normative_id': 'INTEGER'},
                'reports': {'checks': "TEXT NOT NULL DEFAULT '[]'"},
            }
            for table, fields in additions.items():
                present = self._columns(c, table)
                for name, declaration in fields.items():
                    if name not in present:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS reference_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, name TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1, payload TEXT NOT NULL DEFAULT '{}',
              UNIQUE(category,name));
            CREATE TABLE IF NOT EXISTS workflow_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_alerts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id),
              kind TEXT NOT NULL, marker TEXT NOT NULL, message TEXT NOT NULL, created TEXT NOT NULL,
              UNIQUE(task_id,kind,marker));
            CREATE TABLE IF NOT EXISTS alert_acknowledgements(
              alert_id INTEGER NOT NULL REFERENCES task_alerts(id), user_id INTEGER NOT NULL REFERENCES users(id),
              created TEXT NOT NULL, PRIMARY KEY(alert_id,user_id));
            CREATE TABLE IF NOT EXISTS work_sessions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL REFERENCES tasks(id),
              actor_id INTEGER NOT NULL REFERENCES users(id),started TEXT NOT NULL,ended TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_work_session ON work_sessions(task_id) WHERE ended IS NULL;
            ''')
            for key, value in DEFAULT_NOTIFICATIONS.items():
                c.execute('INSERT OR IGNORE INTO workflow_settings(key,value) VALUES(?,?)', (key, str(value)))
            if not c.execute('SELECT 1 FROM reference_items LIMIT 1').fetchone():
                self._seed_references(c)

    @staticmethod
    def _columns(c, table):
        return {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}

    def _seed_references(self, c):
        def add(category, name, **payload):
            payload['demo'] = True
            payload['source'] = 'Условные данные для прототипа; требуют согласования с заказчиком'
            return c.execute('INSERT INTO reference_items(category,name,payload) VALUES(?,?,?)',
                             (category, name, json.dumps(payload, ensure_ascii=False))).lastrowid
        sites = [add('sites', name) for name in
                 ('Горный участок', 'Участок дробления', 'Участок обогащения', 'Ремонтный участок')]
        equipment = [
            ('Экскаватор ЭК-12',0), ('Насос НС-15',0), ('Самосвал СМ-01',0), ('Буровой станок БС-02',0),
            ('Экскаватор ЭК-13',0), ('Дренажный насос ДН-01',0), ('Конвейер ЛК-03',1), ('Конвейер ЛК-01',1),
            ('Дробилка ДР-04',1), ('Дробилка ДР-02',1), ('Дробилка ДР-05',1), ('Питатель ПТ-01',1),
            ('Конвейер ЛК-04',1), ('Аспирационная установка АУ-02',2), ('Грохот ГР-08',2),
            ('Грохот ГР-09',2), ('Сепаратор СП-01',2), ('Вентилятор ВТ-02',2), ('Конвейер ЛК-08',2),
            ('Компрессор КМ-07',3), ('Станок СТ-01',3), ('Сварочный аппарат СА-01',3),
            ('Кран КР-01',3), ('Испытательный стенд ИС-01',3), ('Компрессор КМ-08',3)]
        for name, site in equipment:
            add('equipment', name, site_id=sites[site])
        workers = [r['id'] for r in c.execute("SELECT id FROM users WHERE role='worker' ORDER BY id")]
        for i, name in enumerate(('Демо: механическая бригада', 'Демо: электрическая бригада', 'Демо: ремонтная бригада')):
            add('brigades', name, members=workers[i::3], site_id=sites[i])
        defects={
            'М':('Износ подшипника','Повреждение привода','Вибрация механизма','Ослабление крепежа'),
            'Э':('Нет сигнала','Обрыв цепи','Короткое замыкание','Неисправность датчика'),
            'Г':('Утечка гидравлического масла','Недостаточное давление гидравлики','Повреждение манжеты','Заклинивание гидроклапана'),
            'П':('Утечка воздуха','Недостаточное давление воздуха','Неисправность пневмоклапана','Неисправность осушителя'),
            'С':('Сбой управления','Нарушение подачи материала','Загрязнение','Неисправность не обнаружена')}
        for group,names in defects.items():
            for index,name in enumerate(names,1):
                add('defects',name,code=f'{group}-{index:02d}',group=group)
        materials=[('Смазка','кг'), ('Салфетки','шт.'), ('Датчик','шт.'), ('Кабель','м'),
                   ('Крепёж','шт.'), ('Гидравлическое масло','л'), ('Подшипник','шт.'), ('Ремень привода','шт.'),
                   ('Манжета','шт.'), ('Уплотнительное кольцо','шт.'), ('Фильтр масляный','шт.'), ('Фильтр воздушный','шт.'),
                   ('Шланг гидравлический','м'), ('Фитинг','шт.'), ('Прокладка','шт.'), ('Болт М8','шт.'),
                   ('Болт М10','шт.'), ('Гайка М8','шт.'), ('Гайка М10','шт.'), ('Шайба','шт.'),
                   ('Электроды','кг'), ('Проволока сварочная','кг'), ('Предохранитель','шт.'), ('Реле','шт.'),
                   ('Контактор','шт.'), ('Клемма','шт.'), ('Изоляционная лента','рулон'), ('Термоусадочная трубка','м'),
                   ('Ролик конвейера','шт.'), ('Скребок','шт.'), ('Сетка грохота','м²'), ('Муфта','шт.'),
                   ('Щётка электродвигателя','шт.'), ('Техническое масло','л'), ('Очиститель контактов','л'),
                   ('Ветошь','кг'), ('Стяжка кабельная','шт.'), ('Краска','кг'), ('Антикоррозионный состав','л'), ('Диск отрезной','шт.')]
        for name, unit in materials:
            add('materials', name, unit=unit, price=0)
        for name, hours in [('Демо: осмотр оборудования',1), ('Демо: обслуживание привода',1.5),
                            ('Демо: замена датчика',.5), ('Демо: устранение утечки',2)]:
            add('normatives', name, hours=hours)

    @staticmethod
    def _reference_row(row):
        value = dict(row)
        payload = json.loads(value.pop('payload'))
        return {**payload, **value}

    def _references(self, c, category=None, site=None):
        result = {key: [] for key in REFERENCE_CATEGORIES}
        for row in c.execute('SELECT * FROM reference_items ORDER BY category,name'):
            item = self._reference_row(row)
            if category and item['category'] != category:
                continue
            if site is not None and item['category'] == 'equipment':
                if isinstance(site, str) and not site.isdigit():
                    sr = c.execute("SELECT id FROM reference_items WHERE category='sites' AND name=?", (site,)).fetchone()
                    site_id = sr['id'] if sr else -1
                else:
                    site_id = int(site)
                if item.get('site_id') != site_id:
                    continue
            result[item['category']].append(item)
        return result[category] if category else result

    def references(self, actor, category=None, site=None):
        if category is not None and category not in REFERENCE_CATEGORIES:
            raise ValueError('Неизвестный справочник.')
        with self.transaction() as c:
            u = self.require(c, actor)
            data = self._references(c, category, site)
            if u['role'] != 'admin':
                if category:
                    data = [item for item in data if item['active']]
                else:
                    data = {key: [item for item in items if item['active']] for key, items in data.items()}
            return data

    @staticmethod
    def _active_reference(c, category, ref_id):
        row = c.execute('SELECT * FROM reference_items WHERE id=? AND category=? AND active=1',
                        (ref_id, category)).fetchone()
        if not row:
            raise ValueError('Элемент справочника не найден или отключён.')
        return WorkflowMixin._reference_row(row)

    def _validate_assignment_references(self, c, site, equipment, brigade_id=None, worker_id=None, normative_id=None, strict=False, historical=False):
        sr = c.execute("SELECT * FROM reference_items WHERE category='sites' AND name=? AND active=1", (site,)).fetchone()
        if not sr and not historical:
            raise ValueError('Выберите действующий участок из справочника.')
        er = c.execute("SELECT * FROM reference_items WHERE category='equipment' AND name=? AND active=1", (equipment,)).fetchone()
        if strict and not er:
            raise ValueError('Для выдачи наряда выберите оборудование из справочника.')
        if not historical and er and json.loads(er['payload']).get('site_id') != sr['id']:
            raise ValueError('Оборудование относится к другому участку.')
        if brigade_id:
            brigade = self._active_reference(c, 'brigades', brigade_id)
            if worker_id not in brigade.get('members', []):
                raise ValueError('Ответственный исполнитель должен входить в выбранную бригаду.')
        if normative_id:
            self._active_reference(c, 'normatives', normative_id)

    def save_reference(self, actor, category, item):
        if category not in REFERENCE_CATEGORIES or not isinstance(item, dict):
            raise ValueError('Проверьте справочник и данные.')
        name = str(item.get('name', '')).strip()
        if not 2 <= len(name) <= 200:
            raise ValueError('Название справочника: от 2 до 200 символов.')
        with self.transaction() as c:
            self.require(c, actor, ('admin',)); c.execute('BEGIN IMMEDIATE')
            rid = item.get('id')
            old = c.execute('SELECT * FROM reference_items WHERE id=? AND category=?', (rid, category)).fetchone() if rid else None
            if rid and not old:
                raise ValueError('Элемент справочника не найден.')
            payload = {k: v for k, v in item.items() if k not in ('id','category','name','active')}
            payload['demo'] = bool(payload.get('demo', False))
            if category == 'equipment':
                site_id = payload.get('site_id')
                self._active_reference(c, 'sites', site_id)
            if category == 'brigades':
                members = payload.get('members', [])
                if not isinstance(members, list) or not members:
                    raise ValueError('Укажите хотя бы одного участника бригады.')
                for uid in members:
                    if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1", (uid,)).fetchone():
                        raise ValueError('Бригада содержит недействующего сотрудника.')
                payload['members'] = sorted(set(members))
                if payload.get('site_id'):
                    self._active_reference(c, 'sites', payload['site_id'])
            if category == 'defects' and not str(payload.get('code', '')).strip():
                raise ValueError('Укажите шифр неисправности.')
            if category == 'materials':
                if not str(payload.get('unit', '')).strip():
                    raise ValueError('Укажите единицу измерения.')
                price = float(payload.get('price', 0))
                if not math.isfinite(price) or price < 0:
                    raise ValueError('Цена материала должна быть неотрицательной.')
                payload['price'] = price
            if category == 'normatives':
                hours = float(payload.get('hours', 0))
                if not math.isfinite(hours) or not .1 <= hours <= 24:
                    raise ValueError('Норматив времени: от 0,1 до 24 часов.')
                payload['hours'] = hours
            active = int(bool(item.get('active', True)))
            if old and not active and old['active']:
                raise ValueError('Для отключения элемента используйте удаление: оно проверяет текущие наряды.')
            collision = c.execute('SELECT id FROM reference_items WHERE category=? AND name=?', (category,name)).fetchone()
            if collision and collision['id'] != rid:
                raise ValueError('Такое название уже есть в справочнике.')
            if old:
                # Names are snapshots in historical tasks; renaming never rewrites them.
                c.execute('UPDATE reference_items SET name=?,active=?,payload=? WHERE id=?',
                          (name, active, json.dumps(payload, ensure_ascii=False), rid))
            else:
                rid = c.execute('INSERT INTO reference_items(category,name,active,payload) VALUES(?,?,?,?)',
                                (category, name, active, json.dumps(payload, ensure_ascii=False))).lastrowid
            return self._reference_row(c.execute('SELECT * FROM reference_items WHERE id=?', (rid,)).fetchone())

    def delete_reference(self, actor, category, reference_id):
        if category not in REFERENCE_CATEGORIES:
            raise ValueError('Неизвестный справочник.')
        with self.transaction() as c:
            self.require(c, actor, ('admin',)); c.execute('BEGIN IMMEDIATE')
            item = self._active_reference(c, category, reference_id)
            if category == 'sites':
                if any(r.get('site_id') == reference_id and r['active'] for r in self._references(c, 'equipment')):
                    raise ValueError('Сначала отключите оборудование этого участка.')
            if category in ('sites', 'equipment'):
                column = 'site' if category == 'sites' else 'equipment'
                tasks = c.execute(f'SELECT status FROM tasks WHERE {column}=?', (item['name'],)).fetchall()
                if any(t['status'] in OPEN_TASK_STATUSES for t in tasks):
                    raise ValueError('Справочник используется в текущих нарядах. Сначала завершите или переназначьте работы.')
            if category == 'brigades' and c.execute("SELECT 1 FROM tasks WHERE brigade_id=? AND status NOT IN ('approved','cancelled','rejected')", (reference_id,)).fetchone():
                raise ValueError('У бригады есть текущие наряды.')
            c.execute('UPDATE reference_items SET active=0 WHERE id=?', (reference_id,))
            return True

    def reassign_task(self, actor, tid, worker_id, day, start, reason, brigade_id=None):
        if not 3 <= len(reason.strip()) <= 1000:
            raise ValueError('Укажите причину переназначения: от 3 до 1000 символов.')
        with self.transaction() as c:
            self.require(c, actor, ('master','admin')); c.execute('BEGIN IMMEDIATE')
            task = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
            if not task or task['status'] not in ('available','issued','rejected','accepted','queued','planned') or task['actual_started']:
                raise ValueError('Переназначить можно только не начатый наряд.')
            if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1", (worker_id,)).fetchone():
                raise ValueError('Выберите действующего сотрудника.')
            # Site/equipment are immutable here: old customer labels stay valid.
            self._validate_assignment_references(c, task['site'], task['equipment'], brigade_id, worker_id, historical=True)
            self._schedule(c, worker_id, day, start, task['duration'], tid)
            ending = company_time(day + 'T00:00') + timedelta(hours=start + task['duration'])
            if ending > company_time(task['deadline']):
                raise ValueError('Работа заканчивается позже срока наряда.')
            previous = task['worker_id']
            c.execute("UPDATE tasks SET worker_id=?,brigade_id=?,day=?,start=?,status='issued',issued_at=?,accepted_at=NULL,rejected_reason='' WHERE id=?",
                      (worker_id, brigade_id, day, start, local_stamp(), tid))
            self.event(c, tid, actor['id'], f'Переназначен с исполнителя {previous} на {worker_id}: {reason.strip()}')

    @staticmethod
    def _open_work(c, tid, actor_id):
        stamp = local_stamp()
        c.execute('UPDATE tasks SET actual_started=COALESCE(actual_started,?),completed_at=NULL WHERE id=?', (stamp, tid))
        if not c.execute('SELECT 1 FROM work_sessions WHERE task_id=? AND ended IS NULL', (tid,)).fetchone():
            c.execute('INSERT INTO work_sessions(task_id,actor_id,started) VALUES(?,?,?)', (tid, actor_id, stamp))

    @staticmethod
    def _close_work(c, tid):
        c.execute('UPDATE work_sessions SET ended=? WHERE task_id=? AND ended IS NULL', (local_stamp(), tid))

    @staticmethod
    def _minutes_between(start, end, at=None):
        finish = company_time(end) if end else company_time(at)
        return max(0, (finish-company_time(start)).total_seconds()/60)

    def _timing(self, c, task, at=None):
        sessions = c.execute('SELECT started,ended FROM work_sessions WHERE task_id=?', (task['id'],)).fetchall()
        pauses = c.execute('SELECT started,ended FROM pauses WHERE task_id=?', (task['id'],)).fetchall()
        return {'work_minutes': round(sum(self._minutes_between(s['started'], s['ended'], at) for s in sessions), 1),
                'pause_minutes': round(sum(self._minutes_between(p['started'], p['ended'], at) for p in pauses), 1),
                'timing_recorded': bool(sessions), 'timing_note': 'Пауза по наряду; не подтверждённый простой оборудования'}

    def equipment_history(self, actor, equipment):
        with self.transaction() as c:
            u = self.require(c, actor)
            tasks = c.execute('SELECT * FROM tasks WHERE equipment=? ORDER BY id DESC', (equipment,)).fetchall()
            if u['role'] == 'worker':
                tasks = [t for t in tasks if t['worker_id'] == u['id']]
            out = []
            for row in tasks:
                task = dict(row)
                report = c.execute('SELECT * FROM reports WHERE task_id=? ORDER BY id DESC LIMIT 1', (task['id'],)).fetchone()
                task.update(self._timing(c, task))
                task['last_report'] = None if not report else {
                    'id': report['id'], 'defect': report['defect'], 'result': report['result'],
                    'status': report['status'], 'hours': report['hours'], 'comment': report['comment']}
                task['pauses'] = [dict(p) for p in c.execute('SELECT * FROM pauses WHERE task_id=? ORDER BY id', (task['id'],))]
                out.append(task)
            counts = {}
            for task in out:
                if task['last_report']:
                    defect = task['last_report']['defect'].strip()
                    if defect and defect not in ('Нет', 'Неисправность не обнаружена'):
                        counts[defect] = counts.get(defect, 0) + 1
            return {'equipment': equipment, 'tasks': out,
                    'repeat_defects': [{'defect': key, 'count': value} for key, value in counts.items() if value > 1],
                    'pause_minutes': round(sum(t['pause_minutes'] for t in out), 1)}

    @staticmethod
    def _notification_settings(c):
        return {r['key']: int(r['value']) for r in c.execute('SELECT * FROM workflow_settings')}

    def notification_settings(self, actor):
        with self.transaction() as c:
            self.require(c, actor)
            return {**self._notification_settings(c), 'timezone': 'Asia/Qyzylorda'}

    def set_notification_settings(self, actor, **values):
        if not values or any(k not in DEFAULT_NOTIFICATIONS or isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 1440 for k, v in values.items()):
            raise ValueError('Параметры уведомлений: целое число минут от 1 до 1440.')
        with self.transaction() as c:
            self.require(c, actor, ('admin',))
            for key, value in values.items():
                c.execute('UPDATE workflow_settings SET value=? WHERE key=?', (str(value), key))
        return self.notification_settings(actor)

    def _alert_conditions(self, c, task, at, settings):
        if task['status'] not in OPEN_TASK_STATUSES or task['status'] == 'available' or task['completed_at']:
            return []
        result = []
        deadline = company_time(task['deadline'])
        remaining = (deadline - at).total_seconds()/60
        if remaining < 0:
            result.append(('overdue', task['deadline'], 'Срок выполнения наряда истёк'))
        elif remaining <= settings['reminder_minutes']:
            result.append(('deadline', task['deadline'], f'До срока выполнения осталось {max(0, math.ceil(remaining))} мин.'))
        if task['status'] == 'issued' and task['issued_at']:
            threshold = settings['urgent_accept_minutes'] if task['priority'] == 'urgent' else settings['accept_minutes']
            issued = company_time(task['issued_at'])
            # Acceptance monitoring starts when the worker's scheduled shift starts.
            shift = self._shift(c, task['worker_id'], task['day']) if task['worker_id'] else None
            if shift:
                issued = max(issued, company_time(task['day']+'T00:00') + timedelta(hours=shift['start']))
            if (at - issued).total_seconds() >= threshold * 60:
                result.append(('not_accepted', task['issued_at'], f'Исполнитель не принял наряд за {threshold} мин.; требуется внимание мастера'))
        return result

    def refresh_alerts(self, at=None):
        at = company_time(at)
        with self.transaction() as c:
            settings = self._notification_settings(c)
            for task in c.execute('SELECT * FROM tasks'):
                for kind, marker, message in self._alert_conditions(c, task, at, settings):
                    c.execute('INSERT OR IGNORE INTO task_alerts(task_id,kind,marker,message,created) VALUES(?,?,?,?,?)',
                              (task['id'], kind, marker, message, at.replace(tzinfo=None).isoformat(timespec='seconds')))

    def process_alerts(self, at=None):
        self.refresh_alerts(at)

    def alerts(self, actor, at=None):
        at = company_time(at)
        with self.transaction() as c:
            self.require(c, actor)
        # Refresh on poll and on server timer; persisted rows survive restarts.
        self.refresh_alerts(at)
        with self.transaction() as c:
            u = self.require(c, actor); settings = self._notification_settings(c)
            out = []
            for alert in c.execute('SELECT * FROM task_alerts ORDER BY id DESC'):
                task = c.execute('SELECT * FROM tasks WHERE id=?', (alert['task_id'],)).fetchone()
                if u['role'] == 'worker' and task['worker_id'] != u['id']:
                    continue
                conditions = self._alert_conditions(c, task, at, settings)
                match = next((x for x in conditions if x[:2] == (alert['kind'], alert['marker'])), None)
                if not match:
                    continue
                out.append({**dict(alert), 'message': match[2], 'title': task['title'], 'equipment': task['equipment'],
                            'priority': task['priority'], 'worker_id': task['worker_id'],
                            'acknowledged': bool(c.execute('SELECT 1 FROM alert_acknowledgements WHERE alert_id=? AND user_id=?', (alert['id'], u['id'])).fetchone())})
            return out

    def acknowledge_alert(self, actor, alert_id):
        visible = self.alerts(actor)
        if not any(a['id'] == alert_id for a in visible):
            raise PermissionError('Уведомление не найдено или недоступно.')
        with self.transaction() as c:
            self.require(c, actor)
            c.execute('INSERT OR IGNORE INTO alert_acknowledgements(alert_id,user_id,created) VALUES(?,?,?)',
                      (alert_id, actor['id'], local_stamp()))
        return True

    def attention(self, actor, at=None):
        with self.transaction() as c:
            self.require(c, actor, ('master','admin'))
        alerts = self.alerts(actor, at)
        tasks = self.tasks(actor)
        pauses = []
        repeated = []
        for task in tasks:
            if task['status'] == 'paused':
                history = self.pauses(actor, task['id'])
                pause = next((p for p in history if not p['ended']), None)
                if pause:
                    pauses.append({'task_id': task['id'], 'equipment': task['equipment'], 'reason': pause['reason'],
                                   'minutes': round(self._minutes_between(pause['started'], None, at), 1)})
        for equipment in sorted({t['equipment'] for t in tasks}):
            h = self.equipment_history(actor, equipment)
            if h['repeat_defects']:
                repeated.append({'equipment': equipment, 'defects': h['repeat_defects'], 'task_ids': [t['id'] for t in h['tasks']]})
        return {'alerts': alerts, 'pauses': pauses, 'repeated_equipment': repeated,
                'pending_reports': len([t for t in tasks if t['status'] == 'submitted'])}
