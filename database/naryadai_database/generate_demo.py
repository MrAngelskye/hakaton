"""Synthetic case-1 fixtures. Standard library plus Pillow for labelled test images."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = timezone(timedelta(hours=5))
DEMO_PASSWORD = 'DemoOnly-2026!'
SITE_NAMES = ['Участок дробления', 'Участок обогащения', 'Ремонтно-механический цех', 'Транспортный участок']
EQUIPMENT_NAMES = [
    'Конвейер К-01', 'Дробилка Д-02', 'Грохот ГР-03', 'Питатель П-04', 'Конвейер К-05', 'Дробилка Д-06',
    'Насос Н-07', 'Сепаратор С-08', 'Грохот ГР-09', 'Конвейер К-10', 'Насос Н-11', 'Сепаратор С-12',
    'Токарный станок Т-13', 'Фрезерный станок Ф-14', 'Сварочный пост СП-15', 'Компрессор КМ-16',
    'Кран-балка КБ-17', 'Пресс ПР-18', 'Сверлильный станок СТ-19',
    'Погрузчик ПГ-20', 'Самосвал СМ-21', 'Тягач ТГ-22', 'Погрузчик ПГ-23', 'Самосвал СМ-24', 'Тягач ТГ-25',
]
DEFECT_GROUPS = {
    'М': ('Механика', ['Износ подшипника', 'Ослабление крепления', 'Несоосность привода', 'Повреждение ремня']),
    'Э': ('Электрика', ['Загрязнение контактов', 'Обрыв кабеля', 'Неисправность датчика', 'Перегрев электродвигателя']),
    'Г': ('Гидравлика', ['Утечка масла', 'Падение давления', 'Износ уплотнения', 'Загрязнение фильтра']),
    'П': ('Пневматика', ['Утечка воздуха', 'Неисправность клапана', 'Повреждение шланга', 'Сбой регулятора']),
    'С': ('Смазка', ['Недостаточная смазка', 'Загрязнение масла', 'Засорение канала', 'Повреждение маслёнки']),
}
MATERIAL_NAMES = [
    ('Подшипник 6205','шт.'),('Подшипник 6206','шт.'),('Ремень приводной А-1250','шт.'),('Болт М10','шт.'),
    ('Гайка М10','шт.'),('Шайба М10','шт.'),('Уплотнение насоса','шт.'),('Фильтр масляный','шт.'),
    ('Фильтр воздушный','шт.'),('Шланг гидравлический','м'),('Шланг пневматический','м'),('Кабель силовой','м'),
    ('Датчик индуктивный','шт.'),('Контактор 25А','шт.'),('Предохранитель 10А','шт.'),('Смазка Литол-24','кг'),
    ('Масло гидравлическое','л'),('Масло редукторное','л'),('Очиститель контактов','л'),('Ветошь','кг'),
    ('Электрод сварочный','кг'),('Круг шлифовальный','шт.'),('Круг отрезной','шт.'),('Сверло 10 мм','шт.'),
    ('Кольцо уплотнительное','шт.'),('Манжета гидравлическая','шт.'),('Клапан пневматический','шт.'),('Фитинг','шт.'),
    ('Хомут стальной','шт.'),('Изолента','шт.'),('Клемма кабельная','шт.'),('Трубка термоусадочная','м'),
    ('Муфта приводная','шт.'),('Звено цепи','шт.'),('Ролик конвейера','шт.'),('Сетка фильтрующая','м2'),
    ('Щётка электродвигателя','шт.'),('Прокладка техническая','шт.'),('Фиксатор резьбы','л'),('Паста монтажная','кг'),
]
TABLE_ORDER = ['sites','brigades','equipment','defect_codes','materials','users','shift_rules','shifts',
               'tasks','reports','events','pauses','ai_jobs','report_materials','task_photos','equipment_downtimes','demo_metadata']


def iso(value):
    return value.isoformat(timespec='seconds') if isinstance(value,datetime) else value.isoformat()


def stamp(day,hour):
    return datetime.combine(day,datetime.min.time(),LOCAL)+timedelta(hours=hour)


def three_months_before(day):
    month_index=day.year*12+day.month-1-3
    year,month=divmod(month_index,12)
    import calendar
    return date(year,month+1,min(day.day,calendar.monthrange(year,month+1)[1]))


def sql_value(value):
    if value is None: return 'NULL'
    if isinstance(value,bool): return 'TRUE' if value else 'FALSE'
    if isinstance(value,(int,float)): return str(value)
    if isinstance(value,(list,dict)): value=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return "'"+str(value).replace("'","''")+"'"


def image_card(path,task_id,inventory,kind,report_id):
    from PIL import Image,ImageDraw
    im=Image.new('RGB',(480,300),'#eceff1'); draw=ImageDraw.Draw(im)
    draw.rectangle((16,16,464,284),outline='#424242',width=3)
    draw.text((36,40),'DEMO - SYNTHETIC TEST IMAGE',fill='#b71c1c')
    draw.text((36,80),'NOT A PHOTO OF THE ENTERPRISE',fill='black')
    draw.text((36,125),f'TASK {task_id} / {inventory}',fill='black')
    draw.text((36,165),f'TYPE: {kind.upper()} / REPORT {report_id or "BEFORE"}',fill='black')
    draw.text((36,215),'For storage and workflow tests only',fill='black')
    im.save(path,format='JPEG',quality=80,optimize=True)


def make_data(as_of,count,seed,password,photos_dir):
    if count<500: raise ValueError('The case requires at least 500 historical tasks.')
    rng=random.Random(seed); data={table:[] for table in TABLE_ORDER}
    data['sites']=[{'id':i+1,'code':f'S{i+1:02}','name':name} for i,name in enumerate(SITE_NAMES)]
    data['brigades']=[{'id':i,'code':f'B{i:02}','name':f'Учебная бригада {i}'} for i in range(1,4)]
    for i,name in enumerate(EQUIPMENT_NAMES,1):
        sid=1 if i<=6 else 2 if i<=12 else 3 if i<=19 else 4
        data['equipment'].append({'id':i,'inventory_number':f'DEMO-{i:04}','name':name,'site_id':sid,
                                  'equipment_type':name.split()[0],'criticality':5 if i in (1,7) else rng.randint(1,4)})
    for code,(category,names) in DEFECT_GROUPS.items():
        for number,name in enumerate(names,1):
            data['defect_codes'].append({'id':len(data['defect_codes'])+1,'code':f'{code}-{number:02}',
                                         'name':name,'category':category})
    for i,(name,unit) in enumerate(MATERIAL_NAMES,1):
        data['materials'].append({'id':i,'code':f'MAT-{i:03}','name':name,'unit':unit,'unit_price':float(100+i*137)})
    people=[('master','Демо Мастер 01','Мастер смены','master'),('master2','Демо Мастер 02','Мастер смены','master')]
    people += [(f'worker{i}',f'Демо Исполнитель {i:02}', ['Слесарь','Электрик','Сварщик'][(i-1)%3],'worker') for i in range(1,16)]
    people += [('admin','Демо Администратор','Управление справочниками','admin'),('manager','Демо Руководитель','Руководитель','manager')]
    for i,(username,name,job,role) in enumerate(people,1):
        salt=hashlib.sha256(f'demo-only:{seed}:{username}'.encode()).hexdigest()[:32]
        digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),200_000).hex()
        brigade=((i-3)//5)+1 if role=='worker' else None
        data['users'].append({'id':i,'username':username,'name':name,'job':job,'role':role,'salt':salt,
                              'password_hash':digest,'active':1,'specialty':job,'grade':3+(i%3),'brigade_id':brigade})
        if role=='worker':
            for weekday in range(7):
                data['shift_rules'].append({'worker_id':i,'weekday':weekday,'start':8.,'end':18.})
    first=three_months_before(as_of); days=(as_of-first).days; occupied=set()
    report_id=0; event_id=0; pause_id=0; downtime_id=0

    def event(tid,actor,when,action,old,new,message,reason=''):
        nonlocal event_id
        event_id+=1
        data['events'].append({'id':event_id,'task_id':tid,'actor_id':actor,'message':message,'created':iso(when),
                               'action':action,'from_status':old,'to_status':new,'reason':reason})

    def photo(tid,rid,wid,when,kind):
        key=uuid.uuid5(uuid.NAMESPACE_URL,f'naryadai-demo:{seed}:{tid}:{rid}:{kind}').hex+'.jpg'
        actual=next(t for t in data['tasks'] if t['id']==tid)
        gear=data['equipment'][actual['equipment_id']-1]
        path=photos_dir/key; image_card(path,tid,gear['inventory_number'],kind,rid)
        data['task_photos'].append({'task_id':tid,'report_id':rid,'kind':kind,'object_key':key,'author_id':wid,
                                   'captured_at':iso(when),'uploaded_at':iso(when+timedelta(seconds=10)),
                                   'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'byte_size':path.stat().st_size,'is_demo':True})
        return key

    def add_report(task,finished,defect,hours,score,status,needs_revision=False):
        nonlocal report_id
        report_id+=1; rid=report_id; tid=task['id']; wid=task['worker_id']
        material=data['materials'][0 if defect['code']=='М-01' else 6 if defect['code']=='Г-01' else 19]
        material_rows=[{'name':material['name'],'quantity':1.,'unit':material['unit'],'price':material['unit_price']}]
        grease=data['materials'][15]
        material_rows.append({'name':grease['name'],'quantity':3. if task['equipment_id']==1 else .25,
                              'unit':grease['unit'],'price':grease['unit_price']})
        photo_key=photo(tid,rid,wid,finished-timedelta(minutes=2),'after')
        approved=status=='approved'; reviewed=finished+timedelta(minutes=10) if approved or needs_revision else None
        data['reports'].append({'id':rid,'task_id':tid,'worker_id':wid,
            'work':'[ДЕМО] Выполнена диагностика, заменён изношенный элемент, проверены крепления и выполнен контрольный запуск.',
            'result':'[ДЕМО] Контрольный запуск завершён; запись создана генератором, ремонт на предприятии не проводился.',
            'defect':defect['code']+' · '+defect['name'],'hours':hours,'materials':material_rows,'photos':[photo_key],
            'status':status,'score':score if approved else None,'comment':'[ДЕМО] Учебное решение мастера.' if approved else '[ДЕМО] Требуется уточнить отчёт.',
            'reviewer_id':task['master_id'] if reviewed else None,'created':iso(finished),'reviewed':iso(reviewed) if reviewed else None,
            'defect_code_id':defect['id']})
        for line,m in enumerate(material_rows,1):
            data['report_materials'].append({'report_id':rid,'line_no':line,
                'material_id':next(v['id'] for v in data['materials'] if v['name']==m['name']),
                'name_snapshot':m['name'],'quantity':m['quantity'],'unit':m['unit'],'unit_price':m['price']})
        ai_score=max(40,min(98,score-3 if approved else 55))
        limits={'description':25,'matching':25,'verification':30,'materials_time':20}
        criteria={k:int(ai_score*v/100) for k,v in limits.items()}
        for key in limits:
            addition=min(limits[key]-criteria[key],ai_score-sum(criteria.values())); criteria[key]+=addition
        data['ai_jobs'].append({'report_id':rid,'status':'completed','score':ai_score,
            'verdict':'acceptable' if approved else 'needs_clarification',
            'summary':'[ДЕМО] Синтетическая оценка для тестирования интерфейса. Модель ИИ не вызывалась.',
            'findings':['[ДЕМО] Учебная запись; не подтверждает фактическое состояние оборудования.'],
            'criteria':criteria,'error':'','model':'synthetic-fixture (not LLM)','prompt_version':'demo-v1',
            'created':iso(finished),'finished':iso(finished+timedelta(minutes=1)),
            'lease_token':None,'lease_until':None,'queued_at':finished.timestamp()})
        return rid

    for i in range(count):
        tid=10001+i; day=first+timedelta(days=i%days)
        candidates=([17] if i%10==0 else rng.sample(list(range(3,17)),14))+list(range(3,18))
        selected=None
        for wid in candidates:
            slots=[s for s in (8.,12.,15.) if (wid,day,s) not in occupied]
            if slots: selected=(wid,rng.choice(slots)); break
        if selected is None: raise ValueError('Not enough non-overlapping schedule slots; reduce task count.')
        wid,start=selected; occupied.add((wid,day,start))
        eid=1 if i%6==0 else 7 if i%9==0 else rng.randint(2,25)
        gear=data['equipment'][eid-1]; duration=1.; created=stamp(day,start-.5)
        late=(i%10!=1) if wid==17 else (i%13==0)
        hours=1.6 if late else .8; finished=stamp(day,start+hours)
        task={'id':tid,'title':('[ДЕМО] Устранить неисправность ' if eid in (1,7) or i%3 else '[ДЕМО] Плановый осмотр ')+gear['name'],
              'description':'[ДЕМО] Проверить оборудование, выполнить обслуживание и зафиксировать результаты контрольного запуска.',
              'site':SITE_NAMES[gear['site_id']-1],'equipment':gear['name'],'priority':'urgent' if eid in (1,7) or i%3 else 'normal',
              'kind':'Внеплановая' if eid in (1,7) or i%3 else 'Плановая','duration':duration,'day':iso(day),'start':start,
              'deadline':iso(stamp(day,start+duration)),'worker_id':wid,'master_id':1+i%2,'status':'approved',
              'created':iso(created),'site_id':gear['site_id'],'equipment_id':eid}
        data['tasks'].append(task)
        defect=data['defect_codes'][0 if eid==1 else 8 if eid==7 else rng.randrange(20)]
        event(tid,task['master_id'],created,'issued',None,'planned','[ДЕМО] Наряд выдан мастером.')
        event(tid,wid,created+timedelta(minutes=2),'accepted','planned','planned','[ДЕМО] Исполнитель принял наряд.')
        event(tid,wid,stamp(day,start),'started','planned','inProgress','[ДЕМО] Начато исполнение.')
        if i%8==0:
            pause_id+=1; pause_start=stamp(day,start+.1); pause_end=stamp(day,start+.2)
            data['pauses'].append({'id':pause_id,'task_id':tid,'actor_id':wid,'reason':'[ДЕМО] Ожидание запчасти',
                                   'started':iso(pause_start),'ended':iso(pause_end),'ended_by':wid})
            event(tid,wid,pause_start,'paused','inProgress','paused','[ДЕМО] Пауза: ожидание запчасти.','Ожидание запчасти')
            event(tid,wid,pause_end,'resumed','paused','inProgress','[ДЕМО] Работа продолжена.')
        if i%12==0: photo(tid,None,task['master_id'],created,'before')
        score=rng.randint(72,98)
        if i%11==0:
            old_finished=finished-timedelta(minutes=25)
            add_report(task,old_finished,defect,.4,55,'superseded',True)
            event(tid,wid,old_finished,'submitted','inProgress','aiPending','[ДЕМО] Первая версия отчёта.')
            event(tid,task['master_id'],old_finished+timedelta(minutes=1),'ai_completed','aiPending','submitted','[ДЕМО] Синтетическая оценка первой версии.')
            event(tid,task['master_id'],old_finished+timedelta(minutes=10),'revision','submitted','revision','[ДЕМО] Отчёт возвращён на доработку.')
            event(tid,wid,old_finished+timedelta(minutes=12),'resumed','revision','inProgress','[ДЕМО] Уточнение отчёта.')
        add_report(task,finished,defect,hours,score,'approved')
        event(tid,wid,finished,'submitted','inProgress','aiPending','[ДЕМО] Отчёт передан на проверку.')
        event(tid,task['master_id'],finished+timedelta(minutes=1),'ai_completed','aiPending','submitted','[ДЕМО] Синтетическая оценка ИИ записана.')
        event(tid,task['master_id'],finished+timedelta(minutes=10),'approved','submitted','approved','[ДЕМО] Учебное принятие мастером.')
        if task['kind']=='Внеплановая':
            downtime_id+=1
            data['equipment_downtimes'].append({'id':downtime_id,'equipment_id':eid,'task_id':tid,
                'started_at':iso(created),'ended_at':iso(finished),'reason':'[ДЕМО] '+defect['name'],'defect_code_id':defect['id']})

    # Fresh tasks on the next day keep the prototype immediately usable.
    tomorrow=as_of+timedelta(days=1)
    for i in range(8):
        tid=10001+count+i; gear=data['equipment'][i+1]; wid=3+i
        created=stamp(as_of,14); assigned=i!=0
        task={'id':tid,'title':'[ДЕМО] Проверить '+gear['name'],
            'description':'[ДЕМО] Открытый наряд для проверки назначения, запуска, отчёта и принятия мастером.',
            'site':SITE_NAMES[gear['site_id']-1],'equipment':gear['name'],'priority':'normal','kind':'Плановая','duration':1.,
            'day':iso(tomorrow),'start':8. if assigned else None,'deadline':iso(stamp(tomorrow,18)),
            'worker_id':wid if assigned else None,'master_id':1+i%2,'status':'planned' if assigned else 'available',
            'created':iso(created),'site_id':gear['site_id'],'equipment_id':gear['id']}
        data['tasks'].append(task)
        event(tid,task['master_id'],created,'issued',None,task['status'],'[ДЕМО] Открытый наряд для живой проверки.')

    dataset_id=hashlib.sha256(f'case1-v2:{as_of}:{count}:{seed}:{password}'.encode()).hexdigest()
    data['demo_metadata']=[{'key':'dataset','value':{'dataset_id':dataset_id,'as_of':iso(as_of),'history_from':iso(first),
        'history_until':iso(as_of-timedelta(days=1)),'seed':seed,'historical_tasks':count,'synthetic':True}}]
    stats={k:len(v) for k,v in data.items()}
    patterns={
        'frequent_failures': {'equipment':'Конвейер К-01','explanation':'Повышенная частота внеплановых ремонтов.'},
        'recurring_defect': {'equipment':'Насос Н-07','defect':'Г-01','explanation':'Повторяющиеся записи об утечке масла.'},
        'late_reports': {'username':'worker15','explanation':'Повышенная доля отчётов после срока.'},
        'material_overuse': {'material':'Смазка Литол-24','equipment':'Конвейер К-01','quantity':3.0,'baseline_quantity':.25},
    }
    return data,{'dataset_id':dataset_id,'as_of':iso(as_of),'history_from':iso(first),'history_until':iso(as_of-timedelta(days=1)),
                 'seed':seed,'synthetic':True,'counts':stats,'planted_patterns':patterns}


def write_seed(data,path,dataset_id):
    sql=['-- Synthetic data only. Refuses to merge with a different populated database.','BEGIN;',
         'SET LOCAL search_path TO naryadai,public;',"SET LOCAL TIME ZONE 'Asia/Qyzylorda';",
         "DO $$ BEGIN IF EXISTS(SELECT 1 FROM users) AND NOT EXISTS(SELECT 1 FROM demo_metadata WHERE key='dataset' AND value->>'dataset_id'="+sql_value(dataset_id)+") THEN RAISE EXCEPTION 'Target database is not empty or contains another dataset. Nothing was changed.'; END IF; END $$;"]
    for table in TABLE_ORDER:
        rows=data[table]
        if not rows: continue
        columns=list(rows[0]); values=[ '('+','.join(sql_value(row.get(c)) for c in columns)+')' for row in rows ]
        conflict=' ON CONFLICT DO NOTHING'
        if table=='task_photos':
            conflict=' ON CONFLICT(object_key) DO UPDATE SET captured_at=EXCLUDED.captured_at, uploaded_at=EXCLUDED.uploaded_at, sha256=EXCLUDED.sha256, byte_size=EXCLUDED.byte_size, is_demo=EXCLUDED.is_demo'
        sql.append('INSERT INTO '+table+'('+','.join('"'+c+'"' for c in columns)+') VALUES\n'+',\n'.join(values)+conflict+';')
    for table in ['sites','brigades','equipment','defect_codes','materials','users','tasks','reports','events','pauses','task_photos','equipment_downtimes']:
        sql.append("SELECT setval(pg_get_serial_sequence('naryadai."+table+"','id'),GREATEST(COALESCE((SELECT max(id) FROM "+table+"),1),1),true);")
    sql+=['COMMIT;','']
    path.write_text('\n'.join(sql),encoding='utf-8')


def sqlite_ddl(schema):
    tables=re.findall(r'CREATE TABLE IF NOT EXISTS \w+\s*\(.*?\);',schema,re.S)
    scripts=[]
    for statement in tables:
        statement=statement.replace('BIGSERIAL PRIMARY KEY','INTEGER PRIMARY KEY')
        statement=re.sub(r'\bBIGINT\b','INTEGER',statement)
        statement=statement.replace('DOUBLE PRECISION','REAL').replace('TIMESTAMPTZ','TEXT').replace('JSONB','TEXT')
        statement=re.sub(r'\bDATE\b','TEXT',statement)
        statement=statement.replace(' DEFAULT now()','')
        statement=re.sub(r" CHECK \(jsonb_typeof\((materials|photos)\)='array'\)",'',statement)
        statement=re.sub(r" CHECK \(sha256 IS NULL OR sha256~'\^\[a-f0-9\]\{64\}\$'\)",'',statement)
        scripts.append(statement)
    scripts+=re.findall(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS .*?;',schema,re.S)
    views=re.findall(r'CREATE OR REPLACE VIEW .*?;',schema,re.S)
    scripts += [v.replace('CREATE OR REPLACE VIEW','CREATE VIEW IF NOT EXISTS') for v in views]
    return '\n'.join(scripts)


def write_sqlite(data,path):
    if path.exists(): raise FileExistsError('Refusing to overwrite SQLite: '+str(path))
    with sqlite3.connect(path) as c:
        c.execute('PRAGMA foreign_keys=ON')
        c.executescript(sqlite_ddl((ROOT/'schema.sql').read_text(encoding='utf-8')))
        for table in TABLE_ORDER:
            rows=data[table]
            if not rows: continue
            columns=list(rows[0]); query='INSERT INTO '+table+'('+','.join('"'+v+'"' for v in columns)+') VALUES('+','.join('?' for _ in columns)+')'
            def encoded(v):
                if isinstance(v,(dict,list)): return json.dumps(v,ensure_ascii=False)
                if isinstance(v,str) and re.match(r'^\d{4}-\d{2}-\d{2}T',v):
                    parsed=datetime.fromisoformat(v)
                    if parsed.tzinfo is not None: return parsed.astimezone(LOCAL).replace(tzinfo=None).isoformat(timespec='seconds')
                return v
            c.executemany(query,[tuple(encoded(row.get(k)) for k in columns) for row in rows])
        c.execute("INSERT INTO schema_migrations VALUES('001',?,'SQLite demonstration mirror')",(iso(datetime.now(LOCAL)),))
        violations=c.execute('PRAGMA foreign_key_check').fetchall()
        if violations: raise ValueError(str(violations))
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SQLite integrity check failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of',default='2026-10-04',help='Local reference date YYYY-MM-DD')
    parser.add_argument('--count',type=int,default=600,help='Historical tasks; at least 500')
    parser.add_argument('--seed',type=int,default=20261004)
    parser.add_argument('--output',type=Path,default=ROOT/'generated')
    parser.add_argument('--password-env',help='Environment variable containing a replacement demo password')
    args=parser.parse_args(); output=args.output.resolve()
    if output.exists() and any(output.iterdir()): raise ValueError('Choose a new empty output directory; existing datasets are preserved.')
    password=os.environ.get(args.password_env,'') if args.password_env else DEMO_PASSWORD
    if len(password)<12: raise ValueError('Demo password must contain at least 12 characters.')
    output.mkdir(parents=True,exist_ok=True); photos=output/'photos'; photos.mkdir()
    data,manifest=make_data(date.fromisoformat(args.as_of),args.count,args.seed,password,photos)
    (output/'demo.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_seed(data,output/'seed.sql',manifest['dataset_id'])
    write_sqlite(data,output/'naryadai.db')
    accounts='DEMONSTRATION ACCOUNTS ONLY\nPassword: '+password+'\n\n'+'\n'.join(f"{u['username']} | {u['role']} | {u['name']}" for u in data['users'])+'\n'
    (output/'demo_accounts.txt').write_text(accounts,encoding='utf-8')
    print(json.dumps({'output':str(output),'counts':manifest['counts'],'synthetic':True},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
