"""Verified reference data, never a fabricated plant operational history."""
import json
import re
import secrets
from pathlib import Path


def enrich_users(c, rows):
    metadata = {r['user_id']: dict(r) for r in c.execute('SELECT * FROM account_provenance')}
    for user in rows:
        item = metadata.get(user['id'])
        user['grade_confirmed'] = bool(item['grade_confirmed']) if item else True
        user['identity_status'] = item['identity_status'] if item else 'user_entered'
    return rows


def mark_employee_profile(c, user_id):
    c.execute('UPDATE account_provenance SET grade_confirmed=1 WHERE user_id=?', (user_id,))


def register_user_profile(c, user_id):
    """A newly registered account does not establish an employee's grade or shift."""
    from app.case_store import stamp
    c.execute('INSERT INTO reference_sources(source_id,title,url,publisher,source_kind,retrieved_at,license_id,evidence) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO NOTHING',
              ('OPERATOR-INPUT','Ввод администратора приложения','urn:naryadai:operator-input',
               'Администратор НарядAI','operator_input',stamp(),'facts_only_no_image_rights',
               'Имя и должность введены администратором. Это не публичный источник и не подтверждение разряда или графика.'))
    c.execute('INSERT INTO account_provenance(user_id,source_id,identity_status,grade_confirmed,note) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO NOTHING',
              (user_id,'OPERATOR-INPUT','user_entered',0,
               'Имя и должность введены администратором. Разряд и график ещё не подтверждены.'))


def enrich_catalogs(c, catalogs):
    metadata = {r['material_id']: dict(r) for r in c.execute('SELECT * FROM material_reference_metadata')}
    for material in catalogs['materials']:
        item = metadata.get(material['id'])
        material['unit_price_known'] = bool(item['price_known']) if item else True
        material['reference_only'] = bool(item and not item['company_usage_confirmed'])
        if item:
            material['source_id'] = item['source_id']
            material['reference_note'] = item['note']
    for table in ('work_order_templates', 'equipment_reference_types', 'reference_sources'):
        catalogs[table] = [dict(row) for row in c.execute('SELECT * FROM '+table)]
    return catalogs


def assert_material_priced(c, material_id):
    row = c.execute('SELECT price_known FROM material_reference_metadata WHERE material_id=?', (material_id,)).fetchone()
    if row and not row['price_known']:
        raise ValueError('Цена материала не подтверждена. Администратор должен указать фактическую цену в справочнике; технический ноль не является стоимостью.')


def mark_material_price(c, material_id):
    # An explicit administrator/master save establishes a user-entered price.
    # It does not establish a manufacturer recommendation or factory stock.
    c.execute('UPDATE material_reference_metadata SET price_known=1 WHERE material_id=?', (material_id,))


def load_reference_package(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != 1:
        raise ValueError('Неизвестная версия справочников.')
    sources = {row['source_id']: row for row in payload['sources']}
    if len(sources) != len(payload['sources']):
        raise ValueError('Повторяются идентификаторы источников.')
    for source in sources.values():
        if not source['url'].startswith('https://') or not source['evidence']:
            raise ValueError('Источник должен иметь HTTPS-ссылку и описание проверенного факта.')
    for kind in ('sites', 'job_titles', 'materials', 'equipment_types', 'work_order_templates', 'accounts', 'defect_codes'):
        for row in payload[kind]:
            if row['source_id'] not in sources:
                raise ValueError('Не найден источник записи: '+row['source_id'])
    for row in payload['materials']:
        if row.get('company_usage_confirmed') or row.get('unit_price') is not None or row.get('stock_quantity') is not None:
            raise ValueError('Открытый каталог не подтверждает закупки, цены или остатки предприятия.')
    for row in payload['accounts']:
        # Accept old exported packages too; newly generated logins have no km. prefix.
        if row['role'] not in ('worker', 'master', 'admin', 'manager') or not re.fullmatch(r'(?:km\.)?[a-z]+\.\d{2}', row['username']):
            raise ValueError('Используйте отдельные логины worker.01, master.01, admin.01 или manager.01.')
        if row.get('identity_status') != 'unassigned_anonymized_profile':
            raise ValueError('Публичные имена сотрудников не импортируются как учётные записи.')
        if row.get('identity_origin') not in (None, 'fictional'):
            raise ValueError('ФИО в стартовом справочнике должны быть вымышленными.')
    return payload


def _source(c, row):
    c.execute('INSERT INTO reference_sources(source_id,title,url,publisher,source_kind,retrieved_at,published_at,license_id,evidence) VALUES(?,?,?,?,?,?,?,?,?)',
        (row['source_id'], row['title'], row['url'], row['publisher'], row['source_kind'], row['retrieved_at'],
         row.get('published_at'), row.get('license_id') or 'facts_only_no_image_rights', row['evidence']))


def _provenance(c, kind, key, source, status, note, confirmed=False):
    c.execute('INSERT INTO reference_provenance(entity_type,entity_key,source_id,status,company_confirmed,note) VALUES(?,?,?,?,?,?)',
              (kind, str(key), source, status, int(confirmed), note))


def bootstrap(store, payload, credentials, *, include_catalogs=False):
    """One transaction. Refuse populated DBs; do not relabel demo records as real."""
    from app.store import password_hash
    from app.production_schema import BUSINESS_TABLES
    if len(credentials) != len(payload['accounts']) or len({r['password'] for r in credentials}) != len(credentials):
        raise ValueError('Каждому аккаунту нужен отдельный пароль.')
    passwords = {r['username']: r['password'] for r in credentials}
    if any(len(p) < 20 for p in passwords.values()):
        raise ValueError('Сгенерированные пароли должны содержать не меньше 20 символов.')
    with store.transaction(write=True) as c:
        for table in BUSINESS_TABLES:
            # SQLite Store has no server ai_jobs table until ServerStore starts.
            if table=='ai_jobs' and not getattr(getattr(store,'settings',None),'database_url',''):
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_jobs'").fetchone():continue
            if c.execute('SELECT count(*) FROM '+table).fetchone()[0]:
                raise ValueError('База уже содержит данные. Подготовьте отдельную пустую БД; очистка не выполняется.')
        account_sources = {row['source_id'] for row in payload['accounts']}
        for row in payload['sources']:
            if not include_catalogs and row['source_id'] not in account_sources:continue
            _source(c, row)
        for row in (payload['sites'] if include_catalogs else []):
            c.execute('INSERT INTO sites(code,name) VALUES(?,?)', (row['code'], row['name']))
            _provenance(c, 'sites', row['code'], row['source_id'], 'public_verified', row['note'], True)
        for row in (payload['materials'] if include_catalogs else []):
            c.execute('INSERT INTO materials(code,name,unit,unit_price) VALUES(?,?,?,0)', (row['code'], row['name'], row['unit']))
            mid = c.execute('SELECT id FROM materials WHERE code=?', (row['code'],)).fetchone()[0]
            c.execute('INSERT INTO material_reference_metadata(material_id,source_id,manufacturer,model,note) VALUES(?,?,?,?,?)',
                      (mid, row['source_id'], row['manufacturer'], row['model'], row['note']))
            _provenance(c, 'materials', row['code'], row['source_id'], 'industry_reference', row['note'])
        for row in (payload['defect_codes'] if include_catalogs else []):
            c.execute('INSERT INTO defect_codes(code,name,category) VALUES(?,?,?)', (row['code'], row['name'], row['category']))
            _provenance(c, 'defect_codes', row['code'], row['source_id'], 'editorial_template', 'Внутренняя классификация приложения, не шифры АО «КМ».')
        for row in (payload['equipment_types'] if include_catalogs else []):
            c.execute('INSERT INTO equipment_reference_types(code,name,source_id,company_context,note) VALUES(?,?,?,?,?)',
                      (row['code'], row['name'], row['source_id'], int(row['company_context']), row['note']))
        for row in (payload['work_order_templates'] if include_catalogs else []):
            c.execute('INSERT INTO work_order_templates(template_id,title,equipment_category,kind,problem_description,closeout_requirements,source_id) VALUES(?,?,?,?,?,?,?)',
                      (row['template_id'], row['title'], row['equipment_category'], row['kind'], row['problem_description'],
                       json.dumps(row['closeout_requirements'], ensure_ascii=False), row['source_id']))
            _provenance(c, 'work_order_templates', row['template_id'], row['source_id'], 'editorial_template', 'Черновик для заполнения мастером. Не фактическая заявка предприятия и не утверждённая инструкция.')
        for row in payload['accounts']:
            salt = secrets.token_hex(16)
            c.execute('INSERT INTO users(username,name,job,role,salt,password_hash,specialty) VALUES(?,?,?,?,?,?,?)',
                (row['username'], row['name'], row['job'], row['role'], salt,
                 password_hash(passwords[row['username']], salt), row['job'] if row['role'] == 'worker' else ''))
            uid = c.execute('SELECT id FROM users WHERE username=?', (row['username'],)).fetchone()[0]
            c.execute('INSERT INTO account_provenance(user_id,source_id,identity_status,note) VALUES(?,?,?,?)',
                      (uid, row['source_id'], row['identity_status'], row.get('note') or 'Должностной профиль без установленного физического лица. Разряд, бригада и смена не подтверждены.'))
            note = ('ФИО вымышлено. Источник подтверждает название должности, а не личность. '
                    if row.get('identity_origin') == 'fictional' else '')
            _provenance(c, 'users', row['username'], row['source_id'], 'anonymized_profile', note+'Распределение аккаунтов не является штатным расписанием.')
    return {'users': len(payload['accounts']), 'sites': len(payload['sites']) if include_catalogs else 0,
            'materials': len(payload['materials']) if include_catalogs else 0,
            'work_order_templates': len(payload['work_order_templates']) if include_catalogs else 0,
            'tasks': 0, 'reports': 0, 'equipment': 0}


def make_credentials(payload):
    return [{'username': row['username'], 'role': row['role'], 'name': row['name'], 'password': secrets.token_urlsafe(24)} for row in payload['accounts']]


def import_photo_manifest(store, manifest):
    """Licensing/provenance registry only; reference images never become task photos."""
    allowed = {'CC0-1.0', 'CC-BY-2.0', 'CC-BY-3.0', 'CC-BY-4.0', 'CC-BY-SA-2.0', 'CC-BY-SA-3.0', 'CC-BY-SA-4.0', 'Public-domain-US-government',
               'CC0', 'CC BY 2.0', 'CC BY 2.5', 'CC BY-SA 2.0', 'CC BY-SA 2.5', 'CC BY-SA 3.0', 'CC BY-SA 4.0', 'Public domain'}
    photos=manifest.get('photos',manifest.get('training_photos',[]))
    if not photos:raise ValueError('Фотокаталог пуст.')
    photo_sources={r['source_id']:r for r in photos}
    with store.transaction(write=True) as c:
        for source in manifest.get('sources',manifest.get('reference_sources',[])):
            if not c.execute('SELECT 1 FROM reference_sources WHERE source_id=?', (source['source_id'],)).fetchone():
                normalized=dict(source)
                normalized.setdefault('source_kind',source.get('kind','open_licensed_photo'))
                normalized.setdefault('retrieved_at',source.get('checked_on','2026-10-07'))
                normalized.setdefault('license_id',photo_sources[source['source_id']]['license_id'])
                normalized.setdefault('evidence','Открытая фотография. Лицензия и атрибуция проверены по зафиксированной ревизии: '+source.get('revision_url',source['url']))
                _source(c, normalized)
        for row in photos:
            relative = Path(row['relative_path'])
            if relative.is_absolute() or '..' in relative.parts or '\\' in row['relative_path']:
                raise ValueError('Недопустимый путь фотографии.')
            if row['license_id'] not in allowed or not re.fullmatch('[a-f0-9]{64}', row['sha256']):
                raise ValueError('Лицензия или контрольная сумма не подтверждены.')
            if row.get('company_image') or row.get('training_approved') or row.get('paired_photo_id'):
                raise ValueError('Открытые снимки не являются фото предприятия или подтверждёнными парами до/после.')
            if not row.get('split_group') or not row.get('attribution'):
                raise ValueError('Укажите атрибуцию и группу для предотвращения утечки между выборками.')
            c.execute('INSERT INTO training_photos(photo_id,source_id,original_url,relative_path,sha256,equipment_category,source_reported_condition,observation,license_id,attribution,split_group) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                tuple(row[k] for k in ('photo_id','source_id','original_url','relative_path','sha256','equipment_category','source_reported_condition','observation','license_id','attribution','split_group')))
    return len(photos)
