"""Case-1 business operations, shared by SQLite and PostgreSQL.

SQL is parameterized. Photos are staged before acquiring a database write lock.
Only the outer transaction commits; nested Store calls share that transaction.
"""
import hashlib
import json
import math
import secrets
import shutil
import sqlite3
import threading
from contextlib import contextmanager,closing
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from app.migrations import migrate

TZ=ZoneInfo('Asia/Qyzylorda')
ACTIVE=('available','planned','accepted','queued','rejected','inProgress','paused','revision','aiPending','submitted')
PRIORITIES={'urgent':'Аварийный','high':'Высокий','normal':'Обычный','scheduled':'Плановый'}

def stamp():return datetime.now(TZ).replace(tzinfo=None).isoformat(timespec='seconds')
def moment(value):
    result=datetime.fromisoformat(str(value))
    return result.astimezone(TZ).replace(tzinfo=None) if result.tzinfo else result
def decoded(value, default=None):
    return json.loads(value) if isinstance(value,str) else value if value is not None else default
def j(value):return json.dumps(value,ensure_ascii=False,allow_nan=False)

class SQLiteConnection:
    def __init__(self,raw):self.raw=raw
    def execute(self,sql,args=()):
        if sql.strip().upper().startswith('BEGIN IMMEDIATE') and self.raw.in_transaction:sql='SELECT 1'
        return self.raw.execute(sql,args)
    def executemany(self,sql,rows):return self.raw.executemany(sql,rows)
    def executescript(self,script):
        # sqlite3.executescript commits implicitly. DDL here contains no trigger bodies.
        for sql in script.split(';'):
            if sql.strip():self.execute(sql)

class CaseWorkflow:
    def __init__(self,*args,seed_demo=None,**kwargs):
        # Production is empty by default. Demo fixtures require an explicit opt-in.
        self.seed_demo=getattr(getattr(self,'settings',None),'seed_demo',False) if seed_demo is None else seed_demo
        if type(self.seed_demo) is not bool:raise ValueError('seed_demo должен быть true/false.')
        self._local=threading.local()
        super().__init__(*args,**kwargs)
        if not getattr(getattr(self,'settings',None),'database_url',''):
            with closing(sqlite3.connect(self.path)) as raw:raw.execute('PRAGMA journal_mode=WAL')

    def migrate_case(self):
        postgres=bool(getattr(getattr(self,'settings',None),'database_url',''))
        if postgres:
            with self.transaction(write=True) as c:migrate(c.connection,True)
            return
        if self.path.exists() and self.path.stat().st_size:
            backup=self.directory/'naryadai-before-v2.db'
            if not backup.exists():
                with closing(sqlite3.connect(self.path)) as source,closing(sqlite3.connect(backup)) as target:source.backup(target)
        # SQLite cannot DROP inline constraints. Preserve IDs, extra columns, manual indexes and triggers.
        import re
        with closing(sqlite3.connect(self.path,timeout=15)) as raw:
            raw.row_factory=sqlite3.Row;raw.execute('PRAGMA legacy_alter_table=ON');raw.execute('BEGIN IMMEDIATE')
            try:
                for table in ('equipment','reports','tasks','users','shift_rules','shifts'):
                    found=raw.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                    if not found:continue
                    original=found['sql'];definition=original
                    if table=='equipment':definition=re.sub(r'\bname(\s+TEXT)\s+UNIQUE\b',r'name\1',definition,flags=re.I)
                    elif table=='reports':definition=re.sub(r',\s*FOREIGN KEY\s*\(\s*task_id\s*,\s*worker_id\s*\)\s+REFERENCES\s+tasks\s*\(\s*id\s*,\s*worker_id\s*\)', '',definition,flags=re.I)
                    elif table=='tasks':
                        definition=definition.replace("priority IN ('urgent','normal')","priority IN ('urgent','high','normal','scheduled')")
                        definition=definition.replace("status IN ('available','planned','inProgress','paused','aiPending','submitted','approved','revision','cancelled')","status IN ('available','planned','accepted','queued','rejected','inProgress','paused','aiPending','submitted','approved','revision','cancelled')")
                        definition=definition.replace('start>=0 AND start<24','start>=0 AND start<48').replace('start+duration<=24','start+duration<=48')
                    else:definition=definition.replace('start>=0 AND start<"end" AND "end"<24','start>=0 AND start<24 AND "end">start AND "end"<=start+24')
                    if definition==original:continue
                    extras=[r['sql'] for r in raw.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('trigger','index') AND sql IS NOT NULL",(table,))]
                    definition=re.sub(r'CREATE TABLE(?: IF NOT EXISTS)?\s+'+table+r'\b','CREATE TABLE '+table+'_v2',definition,flags=re.I)
                    raw.execute(definition);raw.execute('INSERT INTO '+table+'_v2 SELECT * FROM '+table);raw.execute('DROP TABLE '+table);raw.execute('ALTER TABLE '+table+'_v2 RENAME TO '+table)
                    for sql in extras:raw.execute(sql)
                migrate(raw,False)
                if raw.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('SQLite migration failed foreign-key validation; the original database was preserved.')
                raw.commit()
            except Exception:raw.rollback();raise

    @contextmanager
    def transaction(self,write=False):
        current=getattr(self._local,'connection',None)
        if current is not None:
            yield current;return
        raw=sqlite3.connect(self.path,timeout=15);raw.row_factory=sqlite3.Row
        raw.execute('PRAGMA foreign_keys=ON');raw.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        self._local.connection=SQLiteConnection(raw);self._local.after_commit=[]
        try:
            yield self._local.connection
            raw.commit()
            for fn in self._local.after_commit:fn()
        except Exception:
            raw.rollback();raise
        finally:self._local.connection=None;self._local.after_commit=[];raw.close()

    def close(self):pass

    def event(self,c,tid,actor_id,message,action='comment',from_status=None,to_status=None,reason='',data=None,actor_kind='user',device_at=None):
        if device_at and moment(device_at)>datetime.now(TZ).replace(tzinfo=None)+timedelta(minutes=5):raise ValueError('Время действия на устройстве находится в будущем.')
        c.execute('INSERT INTO events(task_id,actor_id,message,created,action,from_status,to_status,reason,data,actor_kind,device_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,actor_id,message,stamp(),action,from_status,to_status,reason,j(data or {}),actor_kind,device_at))

    def seed(self):
        if not self.seed_demo:return
        from app.store import SITES,password_hash
        with self.transaction(write=True) as c:
            if c.execute('SELECT count(*) FROM users').fetchone()[0]:return
            for i,name in enumerate(SITES,1):c.execute('INSERT INTO sites(code,name) VALUES(?,?) ON CONFLICT(name) DO NOTHING',(f'S{i:02}',name))
            for i in range(1,4):c.execute('INSERT INTO brigades(code,name) VALUES(?,?) ON CONFLICT(code) DO NOTHING',(f'B{i:02}',f'Демо бригада {i}'))
            accounts=[('master','Демо мастер 1','Мастер смены','master'),('master2','Демо мастер 2','Мастер смены','master')]+[(f'worker{i}',f'Демо сотрудник {i:02}',['Механик','Электрик','Слесарь'][(i-1)%3],'worker') for i in range(1,16)]+[('admin','Администратор','Управление доступом','admin')]
            for username,name,job,role in accounts:
                salt=secrets.token_hex(16)
                c.execute('INSERT INTO users(username,name,job,role,salt,password_hash,specialty,brigade_id) VALUES(?,?,?,?,?,?,?,?)',
                  (username,name,job,role,salt,password_hash(getattr(self,'seed_password','1234'),salt),job if role=='worker' else '',(int(username[6:])-1)//5+1 if role=='worker' else None))
            for worker in c.execute("SELECT id,brigade_id FROM users WHERE role='worker'").fetchall():
                c.executemany('INSERT INTO shift_rules(worker_id,weekday,start,end) VALUES(?,?,8,18)',[(worker['id'],d) for d in range(7)])
                c.execute('INSERT INTO brigade_memberships(worker_id,brigade_id,joined_at) VALUES(?,?,?)',(worker['id'],worker['brigade_id'],stamp()))
            sites=c.execute('SELECT id FROM sites ORDER BY id').fetchall()
            for i in range(25):c.execute('INSERT INTO equipment(inventory_number,name,site_id,equipment_type,criticality) VALUES(?,?,?,?,?)',(f'DEMO-{i+1:03}',f'Демо агрегат {i+1:02}',sites[i%4]['id'],['Дробилка','Конвейер','Насос'][i%3],i%5+1))
            defects=['Дефектов нет','Износ подшипника','Повреждение ремня','Загрязнение фильтра','Отказ датчика','Перегрев двигателя','Обрыв кабеля','Утечка масла','Низкое давление','Разбалансировка','Заклинивание','Износ футеровки','Ослабление креплений','Засор','Вибрация','Сбой управления','Нарушение изоляции','Износ уплотнения','Трещина','Коррозия']
            for i,name in enumerate(defects):c.execute('INSERT INTO defect_codes(code,name,category) VALUES(?,?,?)',(f'D-{i:02}',name,'Демо'))
            for i in range(40):
                name='Смазка Литол-24' if i==0 else f'Демо материал {i+1:02}'
                c.execute('INSERT INTO materials(code,name,unit,unit_price) VALUES(?,?,?,?)',(f'M-{i+1:03}',name,'кг' if i==0 else 'шт.',1000+i*50))

    def task_downtimes(self,actor,tid):
        with self.transaction() as c:
            self.task(actor,tid)
            return [dict(r) for r in c.execute('SELECT * FROM equipment_downtimes WHERE task_id=? ORDER BY id DESC',(tid,))]

    def equipment_history(self,actor,equipment_id):
        if type(equipment_id) is not int:raise ValueError('Укажите ID оборудования.')
        with self.transaction() as c:
            self.require(c,actor,('master','admin'))
            equipment=c.execute('SELECT * FROM equipment WHERE id=?',(equipment_id,)).fetchone()
            if not equipment:raise ValueError('Оборудование не найдено.')
            tasks=[t for t in self.tasks(actor) if t['equipment_id']==equipment_id]
            reports=self.reports(actor,task_ids=[t['id'] for t in tasks])
            for t in tasks:t['last_report']=next((r for r in reports if r['task_id']==t['id'] and r['status']!='superseded'),None)
            downtime=[dict(r) for r in c.execute('SELECT * FROM equipment_downtimes WHERE equipment_id=? ORDER BY id DESC',(equipment_id,))]
            return {'equipment':dict(equipment),'tasks':tasks,'downtimes':downtime}

    def catalogs(self,actor):
        with self.transaction() as c:
            self.require(c,actor)
            result={name:[dict(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY id')] for name in ('sites','equipment','defect_codes','materials','brigades','work_norms','material_norms') if name!='material_norms'} | {'material_norms':[dict(r) for r in c.execute('SELECT * FROM material_norms ORDER BY norm_id,material_id')]}
            from app.production_data import enrich_catalogs
            return enrich_catalogs(c,result)

    def catalog_upsert(self,actor,catalog,values,record_id=None):
        fields={'sites':('code','name'),'equipment':('inventory_number','name','site_id','equipment_type','criticality'),'materials':('code','name','unit','unit_price'),'defect_codes':('code','name','category'),'brigades':('code','name'),'work_norms':('equipment_type','kind','defect_code_id','hours','complexity','active')}
        if catalog not in fields or set(values)!=set(fields[catalog]):raise ValueError('Проверьте поля справочника.')
        if any(isinstance(v,str) and not v.strip() for v in values.values()) or any(isinstance(v,str) and len(v)>200 for v in values.values()):raise ValueError('Заполните поля справочника (до 200 символов).')
        if catalog=='materials' and (not math.isfinite(float(values['unit_price'])) or float(values['unit_price'])<0):raise ValueError('Цена должна быть неотрицательной.')
        if catalog=='equipment' and (type(values['criticality']) is not int or not 1<=values['criticality']<=5):raise ValueError('Критичность: 1–5.')
        if catalog=='work_norms' and (values['kind'] not in ('Плановая','Внеплановая') or not .1<=float(values['hours'])<=24 or not 0<float(values['complexity'])<=10):raise ValueError('Проверьте норматив.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'))
            if record_id:
                if not c.execute('SELECT 1 FROM '+catalog+' WHERE id=?',(record_id,)).fetchone():raise ValueError('Запись не найдена.')
                c.execute('UPDATE '+catalog+' SET '+','.join(k+'=?' for k in fields[catalog])+' WHERE id=?',tuple(values[k] for k in fields[catalog])+(record_id,))
            else:record_id=c.execute('INSERT INTO '+catalog+'('+','.join(fields[catalog])+') VALUES('+','.join('?' for _ in fields[catalog])+')',tuple(values[k] for k in fields[catalog])).lastrowid
            if catalog=='materials':
                from app.production_data import mark_material_price
                mark_material_price(c,record_id)
            return record_id

    def set_material_norm(self,actor,norm_id,material_id,quantity):
        if not math.isfinite(quantity) or quantity<=0:raise ValueError('Норматив расхода должен быть положительным.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'))
            c.execute('INSERT INTO material_norms(norm_id,material_id,quantity) VALUES(?,?,?) ON CONFLICT(norm_id,material_id) DO UPDATE SET quantity=excluded.quantity',(norm_id,material_id,quantity))

    def set_employee_profile(self,actor,wid,specialty,grade,brigade_id=None):
        if len(specialty.strip())<2 or type(grade) is not int or not 1<=grade<=6:raise ValueError('Укажите специальность и разряд 1–6.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('admin',))
            old=c.execute("SELECT * FROM users WHERE id=? AND role='worker'",(wid,)).fetchone()
            if not old:raise ValueError('Сотрудник не найден.')
            if brigade_id and not c.execute('SELECT 1 FROM brigades WHERE id=?',(brigade_id,)).fetchone():raise ValueError('Бригада не найдена.')
            if brigade_id!=old['brigade_id']:
                c.execute('UPDATE brigade_memberships SET left_at=? WHERE worker_id=? AND left_at IS NULL',(stamp(),wid))
                if brigade_id:c.execute('INSERT INTO brigade_memberships(worker_id,brigade_id,joined_at) VALUES(?,?,?)',(wid,brigade_id,stamp()))
            c.execute('UPDATE users SET specialty=?,grade=?,brigade_id=? WHERE id=?',(specialty.strip(),grade,brigade_id,wid))
            from app.production_data import mark_employee_profile
            mark_employee_profile(c,wid)

    def users(self,actor,workers_only=False):
        with self.transaction() as c:
            self.require(c,actor)
            rows=[dict(r) for r in c.execute('SELECT id,username,name,job,role,active,specialty,grade,brigade_id FROM users'+(" WHERE role='worker'" if workers_only else " WHERE role IN ('worker','master','admin')")+' ORDER BY name')]
            from app.production_data import enrich_users
            return enrich_users(c,rows)

    def _visible(self,actor,alias='t'):
        if actor['role']!='worker':return '',()
        return f"({alias}.worker_id=? OR EXISTS(SELECT 1 FROM task_assignments a WHERE a.task_id={alias}.id AND a.worker_id=? AND a.ended_at IS NULL) OR ({alias}.worker_id IS NULL AND {alias}.status='available'))",(actor['id'],actor['id'])

    def tasks(self,actor,since=None,limit=None,offset=0):
        with self.transaction() as c:
            u=self.require(c,actor);where,args=self._visible(u);clauses=[where] if where else []
            if since:clauses.append("(t.day>=? OR t.status NOT IN ('approved','cancelled'))");args+=(since,)
            sql='SELECT t.*,u.name AS worker_name FROM tasks t LEFT JOIN users u ON u.id=t.worker_id'
            if clauses:sql+=' WHERE '+' AND '.join(clauses)
            sql+=" ORDER BY CASE WHEN t.status IN ('approved','cancelled') THEN 1 ELSE 0 END,t.id DESC"
            if limit is not None:sql+=' LIMIT ? OFFSET ?';args+=(limit,offset)
            rows=[dict(r) for r in c.execute(sql,args)]
            # Assignment snapshots, rather than the brigade's current roster.
            members=defaultdict_list(c.execute('SELECT task_id,worker_id FROM task_assignments WHERE ended_at IS NULL'),'task_id','worker_id')
            for row in rows:row['member_ids']=members.get(row['id'],[])
            return rows

    def task(self,actor,tid):
        with self.transaction() as c:
            u=self.require(c,actor);where,args=self._visible(u)
            row=c.execute('SELECT t.*,u.name AS worker_name FROM tasks t LEFT JOIN users u ON u.id=t.worker_id WHERE t.id=?'+(' AND '+where if where else ''),(tid,)+args).fetchone()
            if not row:raise PermissionError('Наряд не найден или недоступен.')
            result=dict(row)
            result['member_ids']=[r['worker_id'] for r in c.execute('SELECT worker_id FROM task_assignments WHERE task_id=? AND ended_at IS NULL',(tid,))]
            return result

    def reports(self,actor,task_ids=None,limit=None,offset=0):
        with self.transaction() as c:
            u=self.require(c,actor);clauses=[];args=()
            if u['role']=='worker':
                clauses.append('(r.worker_id=? OR EXISTS(SELECT 1 FROM task_assignments a WHERE a.task_id=t.id AND a.worker_id=? AND a.ended_at IS NULL))');args=(u['id'],u['id'])
            if task_ids is not None:
                if not task_ids:return []
                clauses.append('r.task_id IN ('+','.join('?' for _ in task_ids)+')');args+=tuple(task_ids)
            sql='SELECT r.*,t.title,t.site,t.equipment,t.deadline,t.kind,t.complexity,t.equipment_id,t.norm_id,u.name AS worker_name,v.name AS reviewer_name FROM reports r JOIN tasks t ON t.id=r.task_id JOIN users u ON u.id=r.worker_id LEFT JOIN users v ON v.id=r.reviewer_id'
            if clauses:sql+=' WHERE '+' AND '.join(clauses)
            sql+=' ORDER BY r.id DESC'
            if limit is not None:sql+=' LIMIT ? OFFSET ?';args+=(limit,offset)
            rows=[dict(r) for r in c.execute(sql,args)]
            for r in rows:
                for key in ('materials','photos','photo_issues'):r[key]=decoded(r[key],[])
            return rows

    @staticmethod
    def _catalog_equipment(c,site,equipment,site_id=None,equipment_id=None):
        s=c.execute('SELECT * FROM sites WHERE '+('id=?' if site_id else 'name=?'),(site_id or site,)).fetchone()
        if not s:raise ValueError('Выберите участок из справочника.')
        rows=c.execute('SELECT * FROM equipment WHERE '+('id=?' if equipment_id else 'name=?')+' AND site_id=?',(equipment_id or equipment,s['id'])).fetchall()
        if len(rows)!=1:raise ValueError('Выберите оборудование из справочника по ID и участку.')
        return dict(s),dict(rows[0])

    @staticmethod
    def _schedule(c,wid,day,start,duration,exclude=-1):
        from app.store import Store
        shift=Store._shift(c,wid,day)
        if not shift:raise ValueError('На этот день сотрудник не на смене.')
        if start is not None and start<shift['start'] and shift['end']>24:start+=24
        if start is None or not math.isfinite(start) or start<shift['start'] or start+duration>shift['end']:raise ValueError('Работа должна помещаться в смену (включая ночную).')
        begin=datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start)
        # Adjacent shift days can overlap after midnight.
        rows=c.execute("SELECT id,day,start,duration FROM tasks t WHERE (worker_id=? OR EXISTS(SELECT 1 FROM task_assignments a WHERE a.task_id=t.id AND a.worker_id=? AND a.ended_at IS NULL)) AND id!=? AND status NOT IN ('cancelled','rejected') AND start IS NOT NULL AND day>=? AND day<=?",(wid,wid,exclude,(date.fromisoformat(day)-timedelta(days=1)).isoformat(),(date.fromisoformat(day)+timedelta(days=1)).isoformat())).fetchall()
        for row in rows:
            other=datetime.combine(date.fromisoformat(row['day']),datetime.min.time())+timedelta(hours=row['start'])
            if begin<other+timedelta(hours=row['duration']) and other<begin+timedelta(hours=duration):raise ValueError('На это время уже назначен другой наряд.')
        return start

    @staticmethod
    def _participants(c,worker_id,brigade_id):
        if brigade_id:
            people=[r['id'] for r in c.execute("SELECT id FROM users WHERE brigade_id=? AND role='worker' AND active=1 ORDER BY id",(brigade_id,))]
            if not people or worker_id and worker_id not in people:raise ValueError('Выберите действующую бригаду и её ведущего исполнителя.')
            return worker_id or people[0],people
        if worker_id:
            if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1",(worker_id,)).fetchone():raise ValueError('Выберите действующего сотрудника.')
            return worker_id,[worker_id]
        return None,[]

    def _assign(self,c,tid,actor,people,brigade_id,reason):
        time=stamp();c.execute('UPDATE task_assignments SET ended_at=? WHERE task_id=? AND ended_at IS NULL',(time,tid))
        for wid in people:
            b=brigade_id or c.execute('SELECT brigade_id FROM users WHERE id=?',(wid,)).fetchone()[0]
            c.execute('INSERT INTO task_assignments(task_id,worker_id,brigade_id,assigned_by,assigned_at,reason) VALUES(?,?,?,?,?,?)',(tid,wid,b,actor['id'],time,reason))

    def create_task(self,actor,*,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id=None,site_id=None,equipment_id=None,brigade_id=None,complexity=1,norm_id=None,photo_sources=()):
        from app.store import STATUS
        if len(title.strip())<5 or len(description.strip())<10:raise ValueError('Заполните название (от 5 символов) и описание (от 10).')
        if not math.isfinite(duration) or not .5<=duration<=10 or priority not in PRIORITIES or kind not in ('Плановая','Внеплановая'):raise ValueError('Проверьте длительность, тип и один из четырёх приоритетов.')
        if not math.isfinite(complexity) or not 0<complexity<=10:raise ValueError('Сложность: больше 0, не больше 10.')
        date.fromisoformat(day)
        if moment(deadline).date()<date.fromisoformat(day):raise ValueError('Срок раньше дня работ.')
        with self.photo_batch(photo_sources) as photos, self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));s,e=self._catalog_equipment(c,site,equipment,site_id,equipment_id)
            wid,people=self._participants(c,worker_id,brigade_id)
            if norm_id:
                norm=c.execute('SELECT * FROM work_norms WHERE id=? AND active=1',(norm_id,)).fetchone()
                if not norm or norm['equipment_type']!=e['equipment_type'] or norm['kind']!=kind:raise ValueError('Норматив не соответствует оборудованию и типу работ.')
                complexity=norm['complexity']
            if people:
                for person in people:start=self._schedule(c,person,day,start,duration)
                end=datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start+duration)
                if end>moment(deadline):raise ValueError('Работа заканчивается позже срока.')
            ts=stamp();status='planned' if wid else 'available'
            tid=c.execute('INSERT INTO tasks(title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,master_id,status,created,site_id,equipment_id,brigade_id,complexity,norm_id,issued_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (title.strip(),description.strip(),s['name'],e['name'],priority,kind,duration,day,start if wid else None,deadline,wid,actor['id'],status,ts,s['id'],e['id'],brigade_id,complexity,norm_id,ts,ts)).lastrowid
            self._assign(c,tid,actor,people,brigade_id,'Выдача наряда')
            self._record_photos(c,tid,None,'before',actor['id'],photos)
            self.event(c,tid,actor['id'],'Выдан наряд','issued',None,status,data={'worker_id':wid,'brigade_id':brigade_id,'priority':priority})
            for person in people:self._notify(c,person,tid,'issued',f'issued:{tid}:{person}',{'title':title,'status':STATUS[status],'priority':priority})
            return tid

    def claim(self,actor,tid,day,start):
        with self.transaction(write=True) as c:
            self.require(c,actor,('worker',));t=self.task(actor,tid)
            if t['status']!='available' or t['worker_id']:raise ValueError('Наряд уже назначен.')
            start=self._schedule(c,actor['id'],day,start,t['duration'],tid)
            if datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start+t['duration'])>moment(t['deadline']):raise ValueError('Выбранное время выходит за срок.')
            c.execute("UPDATE tasks SET worker_id=?,day=?,start=?,status='accepted',accepted_at=?,updated_at=? WHERE id=?",(actor['id'],day,start,stamp(),stamp(),tid))
            self._assign(c,tid,actor,[actor['id']],None,'Самостоятельное принятие')
            self.event(c,tid,actor['id'],'Наряд принят в работу','accepted',t['status'],'accepted')

    def reschedule(self,actor,tid,day,start):
        with self.transaction(write=True) as c:
            u=self.require(c,actor,('worker','master','admin'));t=self.task(actor,tid)
            if u['role']=='worker' and t['worker_id']!=u['id']:raise PermissionError('Только ведущий исполнитель меняет график бригады.')
            if t['status'] not in ('planned','accepted','queued'):raise ValueError('Перенос доступен до начала работы.')
            people=[r['worker_id'] for r in c.execute('SELECT worker_id FROM task_assignments WHERE task_id=? AND ended_at IS NULL',(tid,))] or [t['worker_id']]
            for wid in people:start=self._schedule(c,wid,day,start,t['duration'],tid)
            if datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start+t['duration'])>moment(t['deadline']):raise ValueError('Выбранное время выходит за срок.')
            c.execute('UPDATE tasks SET day=?,start=?,updated_at=? WHERE id=?',(day,start,stamp(),tid))
            self.event(c,tid,actor['id'],'Изменено время в графике','rescheduled',t['status'],t['status'],data={'old_day':t['day'],'old_start':t['start'],'day':day,'start':start})

    def transition(self,actor,tid,status,reason='',device_at=None):
        from app.store import STATUS
        allowed={'planned':{'accepted','queued','rejected','inProgress'},'accepted':{'queued','inProgress','rejected'},'queued':{'accepted','inProgress','rejected'},'inProgress':{'paused'},'paused':{'inProgress'},'revision':{'inProgress'}}
        with self.transaction(write=True) as c:
            u=self.require(c,actor);t=self.task(actor,tid)
            if status=='cancelled':
                self.require(c,actor,('master','admin'))
                if t['status'] not in ACTIVE or t['status'] in ('aiPending','submitted'):raise ValueError('Этот наряд нельзя отменить.')
                reason=reason.strip() or 'Отменён мастером'
                c.execute("UPDATE reports SET status='cancelled' WHERE task_id=? AND status='revision'",(tid,))
            else:
                self.require(c,actor,('worker','admin'))
                member=c.execute('SELECT 1 FROM task_assignments WHERE task_id=? AND worker_id=? AND ended_at IS NULL',(tid,u['id'])).fetchone()
                if not t['worker_id'] or u['role']!='admin' and t['worker_id']!=u['id'] and not member:raise PermissionError('Наряд другого сотрудника.')
                if status not in allowed.get(t['status'],set()):raise ValueError('Действие недоступно в текущем статусе.')
                if status in ('paused','rejected') and not 3<=len(reason.strip())<=1000:raise ValueError('Укажите причину (от 3 до 1000 символов).')
                if status=='inProgress' and c.execute("SELECT 1 FROM tasks t WHERE t.id<>? AND t.status='inProgress' AND (t.worker_id=? OR EXISTS(SELECT 1 FROM task_assignments a WHERE a.task_id=t.id AND a.worker_id=? AND a.ended_at IS NULL))",(tid,u['id'] if u['role']=='worker' else t['worker_id'],u['id'] if u['role']=='worker' else t['worker_id'])).fetchone():raise ValueError('Сначала завершите или приостановите текущую работу.')
            ts=stamp();updates={'status':status,'updated_at':ts}
            if status in ('accepted','queued','inProgress') and not t['accepted_at']:updates['accepted_at']=ts
            if status=='inProgress' and not t['started_at']:updates['started_at']=ts
            if status=='rejected':
                updates.update(rejected_at=ts,refusal_justified=None,rejection_reason=reason.strip())
                who=u['id'] if u['role']=='worker' else t['worker_id']
                assignment=c.execute('SELECT brigade_id FROM task_assignments WHERE task_id=? AND worker_id=? AND ended_at IS NULL',(tid,who)).fetchone()
                c.execute('INSERT INTO task_refusals(task_id,worker_id,brigade_id,assignment_version,created_at,reason) VALUES(?,?,?,?,?,?)',(tid,who,assignment['brigade_id'] if assignment else t['brigade_id'],t['assignment_version'],ts,reason.strip()))
            if status=='queued':updates['queue_position']=c.execute("SELECT COALESCE(MAX(queue_position),0)+1 FROM tasks WHERE worker_id=? AND status='queued'",(t['worker_id'],)).fetchone()[0]
            if status=='paused':c.execute('INSERT INTO pauses(task_id,actor_id,reason,started) VALUES(?,?,?,?)',(tid,actor['id'],reason.strip(),ts))
            if t['status']=='paused':c.execute('UPDATE pauses SET ended=?,ended_by=? WHERE task_id=? AND ended IS NULL',(ts,actor['id'],tid))
            c.execute('UPDATE tasks SET '+','.join(key+'=?' for key in updates)+' WHERE id=?',tuple(updates.values())+(tid,))
            if status=='cancelled':c.execute('UPDATE task_assignments SET ended_at=? WHERE task_id=? AND ended_at IS NULL',(ts,tid))
            self.event(c,tid,actor['id'],STATUS[status]+(': '+reason if reason else ''),status,t['status'],status,reason.strip(),device_at=device_at)
            if status=='rejected':self._notify(c,t['master_id'],tid,'rejected',f'rejected:{tid}:{t["assignment_version"]}',{'reason':reason.strip()})

    def reassign_task(self,actor,tid,worker_id,day,start,reason,brigade_id=None):
        if len(reason.strip())<3:raise ValueError('Укажите причину переназначения.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));t=self.task(actor,tid)
            if t['status'] not in ACTIVE or t['status'] in ('aiPending','submitted'):raise ValueError('Сначала завершите проверку отчёта.')
            wid,people=self._participants(c,worker_id,brigade_id)
            if not wid:raise ValueError('Выберите исполнителя или бригаду.')
            for person in people:start=self._schedule(c,person,day,start,t['duration'],tid)
            if datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start+t['duration'])>moment(t['deadline']):raise ValueError('Назначение выходит за срок.')
            c.execute("UPDATE reports SET status='superseded' WHERE task_id=? AND status='revision'",(tid,))
            c.execute('UPDATE pauses SET ended=?,ended_by=? WHERE task_id=? AND ended IS NULL',(stamp(),actor['id'],tid))
            c.execute("UPDATE tasks SET worker_id=?,brigade_id=?,day=?,start=?,status='planned',issued_at=?,accepted_at=NULL,started_at=NULL,completed_at=NULL,queue_position=NULL,assignment_version=assignment_version+1,updated_at=? WHERE id=?",(wid,brigade_id,day,start,stamp(),stamp(),tid))
            self._assign(c,tid,actor,people,brigade_id,reason.strip())
            self.event(c,tid,actor['id'],'Переназначен наряд','reassigned',t['status'],'planned',reason.strip(),{'old_worker_id':t['worker_id'],'worker_id':wid,'brigade_id':brigade_id})
            for person in people:self._notify(c,person,tid,'assigned',f'assigned:{tid}:{t["assignment_version"]+1}:{person}',{'title':t['title'],'priority':t['priority']})

    def change_priority(self,actor,tid,priority,reason):
        if priority not in PRIORITIES or len(reason.strip())<3:raise ValueError('Выберите приоритет и укажите причину.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));t=self.task(actor,tid)
            if t['status'] in ('approved','cancelled'):raise ValueError('Наряд завершён.')
            c.execute('UPDATE tasks SET priority=?,updated_at=? WHERE id=?',(priority,stamp(),tid))
            self.event(c,tid,actor['id'],'Изменён приоритет','priority_changed',t['status'],t['status'],reason.strip(),{'old_priority':t['priority'],'priority':priority})
            if priority=='urgent' and t['priority']!='urgent':
                people={r['worker_id'] for r in c.execute('SELECT worker_id FROM task_assignments WHERE task_id=? AND ended_at IS NULL',(tid,))}
                if t['worker_id']:people.add(t['worker_id'])
                key=secrets.token_hex(16)
                for uid in people:self._notify(c,uid,tid,'urgent',f'urgent:{key}:{uid}',{'title':t['title'],'priority':priority,'reason':reason.strip()})

    @staticmethod
    def _materials(c,lines):
        if not isinstance(lines,list) or len(lines)>100:raise ValueError('Не больше 100 строк материалов.')
        out=[]
        factors={('г','кг'):Decimal('.001'),('кг','г'):Decimal('1000'),('мл','л'):Decimal('.001'),('л','мл'):Decimal('1000'),('см','м'):Decimal('.01'),('мм','м'):Decimal('.001')}
        for line in lines:
            m=c.execute('SELECT * FROM materials WHERE '+('id=?' if line.get('material_id') else 'name=?'),(line.get('material_id') or line.get('name'),)).fetchone()
            if not m:
                if line.get('material_id'):raise ValueError('Материал не найден в справочнике.')
                name=str(line.get('name','')).strip();unit=str(line.get('unit','')).strip()
                if not 2<=len(name)<=200 or not 1<=len(unit)<=20:raise ValueError('Для своего материала укажите название и единицу измерения.')
                try:qty=Decimal(str(line['quantity']));price=Decimal(str(line.get('price',0)))
                except Exception:raise ValueError('Проверьте количество и цену материала.') from None
                if not qty.is_finite() or not 0<qty<=1000000 or not price.is_finite() or not 0<=price<=100000000:raise ValueError('Проверьте количество и цену материала.')
                out.append({'material_id':None,'name':name,'quantity':float(qty),'unit':unit,'price':float(price),'custom':True})
                continue
            unit=str(line.get('unit','')).strip();factor=Decimal(1) if unit.rstrip('.')==m['unit'].rstrip('.') else factors.get((unit,m['unit']))
            if factor is None:raise ValueError('Единица материала несовместима с единицей справочника.')
            try:qty=Decimal(str(line['quantity']))*factor
            except Exception:raise ValueError('Некорректное количество материала.') from None
            if not qty.is_finite() or not 0<qty<=1000000:raise ValueError('Количество должно быть положительным и конечным.')
            from app.production_data import assert_material_priced
            assert_material_priced(c,m['id'])
            out.append({'material_id':m['id'],'name':m['name'],'quantity':float(qty),'unit':m['unit'],'price':float(m['unit_price'])})
        return out

    @contextmanager
    def photo_batch(self,sources):
        existing=getattr(self._local,'photo_batch',None)
        if existing is not None:
            if list(sources)!=existing['sources']:raise ValueError('Неверная стадия загрузки фото.')
            yield existing;return
        if len(sources)>5:raise ValueError('Можно приложить до 5 фотографий.')
        if getattr(self._local,'connection',None) is not None and sources:raise RuntimeError('Stage photos before database transaction')
        batch={'sources':list(sources),'photos':[],'keep':set()};self._local.photo_batch=batch
        try:
            from PIL import Image
            hashes=set()
            for source in sources:
                p=Path(source)
                if not p.is_file() or p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp') or not 0<p.stat().st_size<=8*1024*1024:raise ValueError('Фото: JPG, PNG, WebP до 8 МБ.')
                try:
                    with Image.open(p) as image:
                        if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>40000000:raise ValueError('Размер фото больше 40 Мп.')
                        image.verify()
                    with Image.open(p) as image:
                        image.load();exif=image.getexif();captured=exif.get(36867) or exif.get(306)
                except (OSError,ValueError,SyntaxError,RuntimeError,Image.DecompressionBombError):raise ValueError('Файл не является поддерживаемым фото.') from None
                sha=hashlib.sha256(p.read_bytes()).hexdigest()
                if sha in hashes:raise ValueError('Одна фотография прикреплена несколько раз.')
                hashes.add(sha);issues=[];capture=None
                if captured:
                    try:capture=datetime.strptime(str(captured),'%Y:%m:%d %H:%M:%S').isoformat(timespec='seconds')
                    except ValueError:issues.append('invalid_exif_time')
                if capture and moment(capture)>datetime.now(TZ).replace(tzinfo=None)+timedelta(minutes=5):raise ValueError('Время съёмки фото находится в будущем.')
                if not capture:issues.append('capture_time_unknown')
                target=self.save_photo(p)
                batch['photos'].append({'object_key':target.name,'target':target,'sha256':sha,'byte_size':p.stat().st_size,'captured_at':capture,'capture_source':'exif_unverified' if capture else 'unknown','issues':issues})
            yield batch
        finally:
            self._local.photo_batch=None
            for photo in batch['photos']:
                if photo['object_key'] not in batch['keep']:
                    try:self.remove_photo(photo['target'])
                    except OSError:pass  # Unreferenced Storage objects can be collected by the maintenance tool.

    def _record_photos(self,c,tid,rid,kind,author,batch):
        issues=[]
        t=c.execute('SELECT issued_at FROM tasks WHERE id=?',(tid,)).fetchone()
        for photo in batch['photos']:
            flags=list(photo['issues'])
            if c.execute('SELECT 1 FROM task_photos WHERE sha256=? AND task_id<>?',(photo['sha256'],tid)).fetchone():flags.append('duplicate_other_task')
            if photo['captured_at'] and t['issued_at'] and moment(photo['captured_at'])<moment(t['issued_at'])-timedelta(minutes=5):flags.append('captured_before_issue')
            c.execute('INSERT INTO task_photos(task_id,report_id,kind,object_key,author_id,uploaded_at) VALUES(?,?,?,?,?,?) ON CONFLICT(object_key) DO NOTHING',(tid,rid,kind,photo['object_key'],author,stamp()))
            c.execute('UPDATE task_photos SET sha256=?,byte_size=?,captured_at=?,capture_source=?,issues=? WHERE object_key=?',(photo['sha256'],photo['byte_size'],photo['captured_at'],photo['capture_source'],j(flags),photo['object_key']))
            issues.extend({'photo':photo['object_key'],'code':flag} for flag in flags)
        keys={photo['object_key'] for photo in batch['photos']}
        self._local.after_commit.append(lambda:batch['keep'].update(keys))
        return issues

    def submit(self,actor,tid,*,work,result,defect,hours,materials,photo_sources,completed_at=None):
        if len(work.strip())<10 or len(result.strip())<3 or not math.isfinite(hours) or not .1<=hours<=24:raise ValueError('Опишите работы, проверку результата и время 0,1–24 часа.')
        with self.photo_batch(photo_sources) as photos, self.transaction(write=True) as c:
            u=self.require(c,actor,('worker','admin'));t=self.task(actor,tid)
            if not t['worker_id'] or u['role']!='admin' and not (t['worker_id']==u['id'] or c.execute('SELECT 1 FROM task_assignments WHERE task_id=? AND worker_id=? AND ended_at IS NULL',(tid,u['id'])).fetchone()):raise PermissionError('Нет доступа к этому наряду.')
            if t['status'] not in ('inProgress','revision'):raise ValueError('Отчёт сейчас нельзя отправить.')
            d=c.execute("SELECT * FROM defect_codes WHERE code=? OR code||' · '||name=?",(defect,defect)).fetchone()
            if not d:raise ValueError('Выберите дефект из справочника.')
            normalized=self._materials(c,materials);end=moment(completed_at) if completed_at else datetime.now(TZ).replace(tzinfo=None)
            if end>datetime.now(TZ).replace(tzinfo=None)+timedelta(minutes=5) or t['started_at'] and end<moment(t['started_at']):raise ValueError('Проверьте фактическое время завершения.')
            c.execute("UPDATE reports SET status='superseded' WHERE task_id=? AND status='revision'",(tid,))
            status=self.initial_report_status(c);keys=[p['object_key'] for p in photos['photos']]
            report_worker=u['id'] if u['role']=='worker' else t['worker_id']
            assignment=c.execute('SELECT brigade_id FROM task_assignments WHERE task_id=? AND worker_id=? AND ended_at IS NULL',(tid,report_worker)).fetchone()
            report_brigade=assignment['brigade_id'] if assignment else t['brigade_id']
            rid=c.execute('INSERT INTO reports(task_id,worker_id,work,result,defect,hours,materials,photos,status,created,defect_code_id,brigade_id,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (tid,report_worker,work.strip(),result.strip(),d['code']+' · '+d['name'],hours,j(normalized),j(keys),status,stamp(),d['id'],report_brigade,end.isoformat(timespec='seconds'))).lastrowid
            c.execute('DELETE FROM report_materials WHERE report_id=?',(rid,))
            for i,line in enumerate(normalized,1):c.execute('INSERT INTO report_materials(report_id,line_no,material_id,name_snapshot,quantity,unit,unit_price) VALUES(?,?,?,?,?,?,?)',(rid,i,line['material_id'],line['name'],line['quantity'],line['unit'],line['price']))
            issues=self._record_photos(c,tid,rid,'after',actor['id'],photos)
            if t['kind']=='Внеплановая' and not keys:issues.append({'code':'mandatory_after_photo_missing'})
            c.execute('UPDATE reports SET photo_issues=? WHERE id=?',(j(issues),rid))
            c.execute('UPDATE tasks SET status=?,completed_at=?,updated_at=? WHERE id=?',(status,end.isoformat(timespec='seconds'),stamp(),tid))
            self.report_submitted(c,rid)
            self.event(c,tid,actor['id'],f'Отправлен отчёт ОТ-{rid:04d}','report_submitted',t['status'],status,data={'report_id':rid,'photo_issues':issues,'completed_at':end.isoformat()})
            self._notify(c,t['master_id'],tid,'report',f'report:{rid}',{'report_id':rid,'photo_issues':issues})
            return rid

    def review(self,actor,rid,approve,score,comment):
        if type(approve) is not bool or len(comment.strip())<3 or approve and (type(score) is not int or not 0<=score<=100):raise ValueError('Укажите решение, комментарий и оценку 0–100.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));r=c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone()
            if not r or r['status']!='submitted':raise ValueError('Отчёт уже проверен или отсутствует.')
            t=self.task(actor,r['task_id'])
            if t['status']!='submitted':raise ValueError('Статус наряда изменился.')
            keys=decoded(r['photos'],[])
            if approve and t['kind']=='Внеплановая' and not keys:raise ValueError('Внеплановый наряд нельзя закрыть без фото после ремонта. Верните отчёт на доработку.')
            if approve and any(not c.execute("SELECT 1 FROM task_photos WHERE task_id=? AND report_id=? AND kind='after' AND object_key=?",(t['id'],rid,key)).fetchone() for key in keys):raise ValueError('Метаданные фото отчёта отсутствуют.')
            status='approved' if approve else 'revision';ts=stamp()
            c.execute('UPDATE reports SET status=?,score=?,comment=?,reviewer_id=?,reviewed=? WHERE id=?',(status,score if approve else None,comment.strip(),actor['id'],ts,rid))
            c.execute('UPDATE tasks SET status=?,closed_at=?,updated_at=? WHERE id=?',(status,ts if approve else None,ts,t['id']))
            self.event(c,t['id'],actor['id'],('Работа закрыта' if approve else 'На доработку')+': '+comment.strip(),'closed' if approve else 'revision',t['status'],status,comment.strip(),{'report_id':rid,'score':score if approve else None})
            self._notify(c,r['worker_id'],t['id'],status,f'review:{rid}:{status}',{'comment':comment.strip(),'score':score if approve else None})

    def events(self,actor,tid):
        with self.transaction() as c:
            self.task(actor,tid)
            rows=[dict(r) for r in c.execute("SELECT e.*,CASE WHEN e.actor_kind='user' THEN u.name ELSE 'Система / интеграция' END AS name FROM events e JOIN users u ON u.id=e.actor_id WHERE e.task_id=? ORDER BY e.id",(tid,))]
            for r in rows:r['data']=decoded(r['data'],{})
            return rows

    def photos_for_task(self,actor,tid):
        with self.transaction() as c:
            self.task(actor,tid);rows=[dict(r) for r in c.execute('SELECT * FROM task_photos WHERE task_id=? ORDER BY id',(tid,))]
            for r in rows:r['issues']=decoded(r['issues'],[])
            return rows

    def can_read_photo(self,actor,name):
        with self.transaction() as c:
            row=c.execute('SELECT task_id FROM task_photos WHERE object_key=?',(name,)).fetchone()
            if not row:return False
            try:self.task(actor,row['task_id']);return True
            except PermissionError:
                return bool(c.execute('SELECT 1 FROM reports r JOIN task_photos p ON p.report_id=r.id WHERE p.object_key=? AND r.worker_id=?',(name,actor['id'])).fetchone())

    def ai_context(self,c,task,report):
        report['photo_issues']=decoded(report.get('photo_issues'),[])
        report['before_photos']=[r['object_key'] for r in c.execute("SELECT object_key FROM task_photos WHERE task_id=? AND kind='before' ORDER BY id",(task['id'],))]
        task['norms']={}
        if task.get('norm_id'):
            norm=c.execute('SELECT hours,complexity FROM work_norms WHERE id=?',(task['norm_id'],)).fetchone()
            if norm:task['norms']={'time':dict(norm),'materials':[dict(r) for r in c.execute('SELECT mn.quantity,m.name,m.unit FROM material_norms mn JOIN materials m ON m.id=mn.material_id WHERE mn.norm_id=?',(task['norm_id'],))]}
        task['historical_context']=[dict(row) for row in c.execute("SELECT t.id,t.title,t.status,t.kind,r.result,r.defect,r.score FROM tasks t LEFT JOIN reports r ON r.task_id=t.id AND r.status='approved' WHERE t.equipment_id=? AND t.id<>? ORDER BY t.id DESC LIMIT 3",(task.get('equipment_id'),task['id']))]
        # Do not send employee names/usernames in free text to an external model.
        import re
        replacements=[(r['name'],f'Сотрудник #{r["id"]}') for r in c.execute('SELECT id,name FROM users')]
        def anonymize(value):
            for name,replacement in replacements:value=value.replace(name,replacement)
            value=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[email]',value)
            return value
        task={**task,'title':anonymize(task['title']),'description':anonymize(task['description'])}
        task['historical_context']=[{k:anonymize(v) if isinstance(v,str) else v for k,v in row.items()} for row in task['historical_context']]
        report={**report,'work':anonymize(report['work']),'result':anonymize(report['result'])}
        return task,report

    def assistant_context(self,actor):
        with self.transaction() as c:
            self.require(c,actor,('master','admin'))
            end=(date.today()+timedelta(days=1)).isoformat();start=(date.today()-timedelta(days=6)).isoformat()
            analytics=self.analytics(actor,start,end);people=self.users(actor,True);statuses=self.availability(actor,date.today().isoformat())[2]
            return {'period':{'start':start,'end_exclusive':end},'counts':analytics['counts'],
               'workers_now':[{'worker_id':p['id'],'specialty':p['specialty'] or p['job'],'status':statuses.get(str(p['id']),'off')} for p in people if p['active']],
               'equipment_failures':analytics['failures'][:10],'downtime':analytics['equipment_downtime'][:10],
               'materials':analytics['materials'][:20],'material_overuse':analytics['material_overuse'][:10],
               'coverage':analytics['coverage'],'note':'Read-only calculated facts. Cite task IDs. Current workers use anonymous IDs. Counts of repairs do not prove causes of physical failures.'}

    def set_shift(self,actor,wid,day,start=None,end=None):
        date.fromisoformat(day)
        if (start is None)!=(end is None):raise ValueError('Укажите начало и конец смены.')
        if start is not None:
            if not all(math.isfinite(v) for v in (start,end)) or not 0<=start<24 or not 0<=end<=48 or start==end:raise ValueError('Проверьте часы смены.')
            if end<start:end+=24
            if not start<end<=start+24:raise ValueError('Смена не длиннее 24 часов.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'))
            if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1",(wid,)).fetchone():raise ValueError('Сотрудник не найден.')
            rows=c.execute("SELECT start,duration FROM tasks WHERE worker_id=? AND day=? AND status NOT IN ('cancelled','rejected') AND start IS NOT NULL",(wid,day)).fetchall()
            if any(start is None or r['start']<start or r['start']+r['duration']>end for r in rows):raise ValueError('Новая смена исключает назначенные работы.')
            c.execute('INSERT INTO shifts(worker_id,day,start,end,updated_by,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(worker_id,day) DO UPDATE SET start=excluded.start,end=excluded.end,updated_by=excluded.updated_by,updated=excluded.updated',(wid,day,start,end,actor['id'],stamp()))

    def start_downtime(self,actor,tid,reason,started_at=None):
        if len(reason.strip())<3:raise ValueError('Укажите причину простоя оборудования.')
        time=moment(started_at) if started_at else datetime.now(TZ).replace(tzinfo=None)
        if time>datetime.now(TZ).replace(tzinfo=None)+timedelta(minutes=5):raise ValueError('Начало простоя в будущем.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('worker','master','admin'));t=self.task(actor,tid)
            if actor['role']=='worker' and actor['id'] not in t['member_ids']:raise PermissionError('Простой регистрирует назначенный исполнитель или мастер.')
            if t['status'] in ('approved','cancelled'):raise ValueError('Наряд завершён.')
            if c.execute('SELECT 1 FROM equipment_downtimes WHERE task_id=? AND ended_at IS NULL',(tid,)).fetchone():raise ValueError('Открытый простой уже зарегистрирован.')
            rid=c.execute('INSERT INTO equipment_downtimes(equipment_id,task_id,started_at,reason) VALUES(?,?,?,?)',(t['equipment_id'],tid,time.isoformat(timespec='seconds'),reason.strip())).lastrowid
            c.execute('UPDATE tasks SET failure_at=COALESCE(failure_at,?),updated_at=? WHERE id=?',(time.isoformat(timespec='seconds'),stamp(),tid))
            self.event(c,tid,actor['id'],'Начало простоя оборудования','downtime_started',t['status'],t['status'],reason.strip(),{'downtime_id':rid,'started_at':time.isoformat()})
            return rid

    def end_downtime(self,actor,downtime_id,ended_at=None):
        time=moment(ended_at) if ended_at else datetime.now(TZ).replace(tzinfo=None)
        if time>datetime.now(TZ).replace(tzinfo=None)+timedelta(minutes=5):raise ValueError('Окончание простоя в будущем.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('worker','master','admin'));r=c.execute('SELECT * FROM equipment_downtimes WHERE id=?',(downtime_id,)).fetchone()
            if not r or r['ended_at'] or time<moment(r['started_at']):raise ValueError('Проверьте интервал простоя.')
            t=self.task(actor,r['task_id']);c.execute('UPDATE equipment_downtimes SET ended_at=? WHERE id=?',(time.isoformat(timespec='seconds'),downtime_id))
            if actor['role']=='worker' and actor['id'] not in t['member_ids']:raise PermissionError('Нет назначения на этот наряд.')
            self.event(c,t['id'],actor['id'],'Окончание простоя оборудования','downtime_ended',t['status'],t['status'],data={'downtime_id':downtime_id,'ended_at':time.isoformat()})

    def assess_refusal(self,actor,tid,justified,reason):
        if type(justified) is not bool or len(reason.strip())<3:raise ValueError('Укажите обоснованность отказа и пояснение.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));t=self.task(actor,tid)
            if not t['rejected_at']:raise ValueError('Отказ по наряду не зарегистрирован.')
            refusal=c.execute('SELECT id FROM task_refusals WHERE task_id=? ORDER BY id DESC LIMIT 1',(tid,)).fetchone()
            if not refusal:raise ValueError('Нет структурированного отказа для оценки.')
            c.execute('UPDATE task_refusals SET justified=?,assessed_by=?,assessed_at=?,assessment_reason=? WHERE id=?',(int(justified),actor['id'],stamp(),reason.strip(),refusal['id']))
            c.execute('UPDATE tasks SET refusal_justified=? WHERE id=?',(int(justified),tid))
            self.event(c,tid,actor['id'],'Оценён отказ','refusal_assessed',t['status'],t['status'],reason.strip(),{'justified':justified,'refusal_id':refusal['id']})

    def confirm_repeat(self,actor,tid,previous_task_id,reason):
        if len(reason.strip())<3:raise ValueError('Укажите основание связи повторной поломки.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));t=self.task(actor,tid);previous=self.task(actor,previous_task_id)
            if tid==previous_task_id or t['equipment_id']!=previous['equipment_id'] or not t['failure_at'] or not previous['completed_at'] or not timedelta(0)<=moment(t['failure_at'])-moment(previous['completed_at'])<=timedelta(days=7):raise ValueError('Связь требует то же оборудование и отказ в течение 7 суток после ремонта.')
            c.execute('UPDATE tasks SET repeat_of_task_id=?,repeat_confirmed_by=? WHERE id=?',(previous_task_id,actor['id'],tid))
            self.event(c,tid,actor['id'],'Подтверждена повторная поломка','repeat_confirmed',t['status'],t['status'],reason.strip(),{'previous_task_id':previous_task_id})

    def _notify(self,c,uid,tid,kind,key,payload):
        c.execute('INSERT INTO notification_outbox(user_id,task_id,event_key,kind,payload,created_at,next_attempt_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING',(uid,tid,key,kind,j(payload),stamp(),stamp()))

    def notification_tick(self,at=None):
        clock=moment(at) if at else datetime.now(TZ).replace(tzinfo=None);settings=getattr(self,'settings',None)
        normal=getattr(settings,'acceptance_minutes',10);urgent=getattr(settings,'urgent_acceptance_minutes',3);remind=getattr(settings,'deadline_reminder_minutes',30);repeat=getattr(settings,'overdue_repeat_minutes',30)
        with self.transaction(write=True) as c:
            assignments=defaultdict_list(c.execute('SELECT task_id,worker_id FROM task_assignments WHERE ended_at IS NULL'),'task_id','worker_id')
            rows=c.execute("SELECT * FROM tasks WHERE status NOT IN ('approved','cancelled','aiPending','submitted')").fetchall()
            for t in rows:
                if not t['issued_at']:continue
                people=set(assignments.get(t['id'],[])) if t['status']!='rejected' else set()
                if t['worker_id'] and t['status']!='rejected':people.add(t['worker_id'])
                people.add(t['master_id'])
                due=moment(t['deadline']);payload={'title':t['title'],'deadline':t['deadline'],'status':t['status'],'priority':t['priority']}
                version=f'{t["id"]}:{t["assignment_version"]}'
                if t['status'] in ('available','planned') and not t['accepted_at'] and clock-moment(t['issued_at'])>=timedelta(minutes=urgent if t['priority']=='urgent' else normal):
                    for uid in {t['master_id']}:self._notify(c,uid,t['id'],'unaccepted',f'unaccepted:{version}:{uid}',payload)
                if timedelta(0)<due-clock<=timedelta(minutes=remind):
                    for uid in people:self._notify(c,uid,t['id'],'deadline_reminder',f'reminder:{version}:{t["deadline"]}:{uid}',payload)
                if due<=clock:
                    bucket=int((clock-due).total_seconds()//(repeat*60))
                    for uid in people:self._notify(c,uid,t['id'],'overdue',f'overdue:{version}:{t["deadline"]}:{bucket}:{uid}',payload)

            # One next job per free employee, including brigade members and night shifts.
            busy=set();candidates={}
            for t in rows:
                owners=set(assignments.get(t['id'],[]))
                if t['worker_id']:owners.add(t['worker_id'])
                if t['status'] in ('inProgress','paused'):busy.update(owners)
                if t['status'] not in ('planned','accepted','queued') or t['start'] is None:continue
                begin=datetime.combine(date.fromisoformat(t['day']),datetime.min.time())+timedelta(hours=float(t['start']))
                if begin>clock+timedelta(minutes=10) or moment(t['deadline'])<=clock:continue
                rank=({'urgent':0,'high':1,'normal':2,'scheduled':3}.get(t['priority'],2),begin,t['queue_position'] or 0,t['id'])
                for uid in owners:
                    if uid not in candidates or rank<candidates[uid][0]:candidates[uid]=(rank,t)
            for uid,(_,t) in candidates.items():
                if uid in busy:continue
                if not c.execute('SELECT 1 FROM users WHERE id=? AND active=1',(uid,)).fetchone():continue
                on_shift=False
                for shift_day in (clock.date(),clock.date()-timedelta(days=1)):
                    shift=self._shift(c,uid,shift_day.isoformat())
                    if shift:
                        base=datetime.combine(shift_day,datetime.min.time())
                        if base+timedelta(hours=float(shift['start']))<=clock<base+timedelta(hours=float(shift['end'])):on_shift=True
                if not on_shift:continue
                key=f'next:{t["id"]}:{t["assignment_version"]}:{t["day"]}:{t["start"]}:{uid}'
                self._notify(c,uid,t['id'],'next_task',key,{'title':t['title'],'priority':t['priority'],'day':t['day'],'start':t['start']})

    def notifications(self,actor,limit=100):
        from app.notification_content import notification_content
        if not 1<=limit<=200:raise ValueError('Лимит уведомлений: 1–200.')
        with self.transaction() as c:
            self.require(c,actor);rows=[dict(r) for r in c.execute('SELECT id,task_id,kind,payload,created_at,read_at FROM notification_outbox WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT ?',(actor['id'],limit))]
            for row in rows:
                row['payload']=decoded(row['payload'],{});row.update(notification_content(row))
            return rows

    def send_announcement(self,actor,title,message,user_ids=None,important=False):
        if not isinstance(title,str) or not 3<=len(title.strip())<=120:raise ValueError('Заголовок: от 3 до 120 символов.')
        if not isinstance(message,str) or not 3<=len(message.strip())<=2000:raise ValueError('Сообщение: от 3 до 2000 символов.')
        if type(important) is not bool:raise ValueError('Проверьте важность сообщения.')
        if user_ids is not None and (not isinstance(user_ids,list) or not 1<=len(user_ids)<=500 or any(type(uid) is not int for uid in user_ids)):raise ValueError('Выберите получателей.')
        with self.transaction(write=True) as c:
            sender=self.require(c,actor,('master','admin'))
            available={r['id'] for r in c.execute("SELECT id FROM users WHERE active=1 AND role='worker'")}
            recipients=available if user_ids is None else set(user_ids)
            if not recipients or not recipients<=available:raise ValueError('Оповещение можно отправить действующим сотрудникам.')
            key=secrets.token_hex(16)
            payload={'title':title.strip(),'message':message.strip(),'important':important,'sender_id':sender['id'],'sender_name':sender['name']}
            for uid in sorted(recipients):self._notify(c,uid,None,'announcement',f'announcement:{key}:{uid}',payload)
            return {'recipients':len(recipients)}

    def acknowledge_notifications(self,actor,notification_ids):
        if not isinstance(notification_ids,list) or not 1<=len(notification_ids)<=200 or any(type(nid) is not int for nid in notification_ids):raise ValueError('Выберите уведомления (до 200).')
        with self.transaction(write=True) as c:
            self.require(c,actor)
            for nid in set(notification_ids):self.acknowledge_notification(actor,nid)

    def acknowledge_notification(self,actor,notification_id):
        with self.transaction(write=True) as c:
            self.require(c,actor)
            if not c.execute('SELECT 1 FROM notification_outbox WHERE id=? AND user_id=?',(notification_id,actor['id'])).fetchone():raise PermissionError('Уведомление другого пользователя.')
            c.execute('UPDATE notification_outbox SET read_at=? WHERE id=?',(stamp(),notification_id))

    @staticmethod
    def _availability(people,tasks,rules,overrides,day,at):
        def shift_for(wid,day):
            value=overrides.get((wid,day))
            if value is not None:return value if value['start'] is not None else None
            return rules.get((wid,date.fromisoformat(day).weekday()))
        shifts={};slots={};statuses={};today=at.date().isoformat();hour=at.hour+at.minute/60+at.second/3600
        for person in people:
            wid=person['id'];s=shift_for(wid,day);shifts[str(wid)]=s
            owned=[t for t in tasks if t['worker_id']==wid or wid in t.get('member_ids',[])]
            current=shift_for(wid,today);previous=shift_for(wid,(at.date()-timedelta(days=1)).isoformat())
            working=bool(current and current['start']<=hour<current['end'] or previous and previous['end']>24 and hour<previous['end']-24)
            status='off' if not person['active'] or not working else 'busy' if any(t['status'] in ('inProgress','paused') for t in owned) else 'queued' if any(t['status'] in ('planned','accepted','queued','revision') for t in owned) else 'free'
            statuses[str(wid)]=status
            periods=[]
            if s and date.fromisoformat(day)>=at.date():
                cursor=s['start']
                if day==today:cursor=max(cursor,math.ceil((hour*60)/5)*5/60)
                # Clip adjacent-day reservations against the selected shift.
                startday=datetime.combine(date.fromisoformat(day),datetime.min.time())
                ranges=[]
                for t in owned:
                    if t['status'] in ('cancelled','rejected') or t['start'] is None:continue
                    a=(datetime.combine(date.fromisoformat(t['day']),datetime.min.time())-startday).total_seconds()/3600+t['start'];b=a+t['duration']
                    if b>s['start'] and a<s['end']:ranges.append((a,b,t['status']))
                if not(day==today and any(status in ('inProgress','paused') and b<=cursor for a,b,status in ranges)):
                    for a,b,_ in sorted(ranges):
                        if a>cursor:periods.append((cursor,min(a,s['end'])))
                        cursor=max(cursor,b)
                    if cursor<s['end']:periods.append((cursor,s['end']))
            slots[str(wid)]=[(a,b) for a,b in periods if b-a>=.5-1e-8]
        return shifts,slots,statuses

    def availability(self,actor,day,at=None,tasks=None,people=None):
        at=at or datetime.now(TZ).replace(tzinfo=None)
        with self.transaction() as c:
            self.require(c,actor)
            people=people if people is not None else self.users(actor,True)
            if actor['role']=='worker':people=[p for p in people if p['id']==actor['id']]
            if tasks is None:
                visible,args=self._visible(actor)
                days=[date.fromisoformat(day),at.date()];minimum=(min(days)-timedelta(days=1)).isoformat();maximum=(max(days)+timedelta(days=1)).isoformat()
                sql="SELECT t.id,t.worker_id,t.day,t.start,t.duration,t.status FROM tasks t WHERE (t.status NOT IN ('approved','cancelled') OR (t.day>=? AND t.day<=?))"+(' AND '+visible if visible else '')
                tasks=[dict(r) for r in c.execute(sql,(minimum,maximum)+args)]
            members=defaultdict_list(c.execute('SELECT task_id,worker_id FROM task_assignments WHERE ended_at IS NULL'),'task_id','worker_id')
            for t in tasks:t['member_ids']=members.get(t['id'],[])
            rules={(r['worker_id'],r['weekday']):{'start':r['start'],'end':r['end']} for r in c.execute('SELECT * FROM shift_rules')}
            days=sorted({day,at.date().isoformat(),(at.date()-timedelta(days=1)).isoformat()})
            overrides={(r['worker_id'],r['day']):{'start':r['start'],'end':r['end']} for r in c.execute('SELECT * FROM shifts WHERE day IN ('+','.join('?' for _ in days)+')',tuple(days))}
            return self._availability(people,tasks,rules,overrides,day,at)

    def free_slots(self,actor,wid,day,at=None):
        if actor['role']=='worker' and wid!=actor['id']:raise PermissionError('Доступен только собственный график.')
        return self.availability(actor,day,at)[1].get(str(wid),[])

    def employee_status(self,actor,wid,at=None):
        if actor['role']=='worker' and wid!=actor['id']:raise PermissionError('Доступен только собственный статус.')
        at=at or datetime.now(TZ).replace(tzinfo=None)
        return self.availability(actor,at.date().isoformat(),at)[2].get(str(wid),'off')

    def analytics(self,actor,start,end,**filters):
        from app.analytics import period_analytics
        return period_analytics(self,actor,start,end,**filters)

    def metrics(self,actor,start=None,end=None):
        end=end or (date.today()+timedelta(days=1)).isoformat();start=start or (date.today()-timedelta(days=90)).isoformat()
        with self.transaction() as c:
            result=self.analytics(actor,start,end)['workers'];statuses=self.availability(actor,date.today().isoformat())[2]
            for r in result:r['employee_status']=statuses.get(str(r['id']),'off')
            return result

    def support_update_task(self,actor,tid,*,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,reason,equipment_id=None,site_id=None):
        if len(reason.strip())<3 or len(title.strip())<5 or len(description.strip())<10 or priority not in PRIORITIES or kind not in ('Плановая','Внеплановая') or not math.isfinite(duration) or not .5<=duration<=10:raise ValueError('Проверьте поля и причину исправления.')
        date.fromisoformat(day)
        if moment(deadline).date()<date.fromisoformat(day):raise ValueError('Срок раньше даты работ.')
        with self.transaction(write=True) as c:
            self.require(c,actor,('master','admin'));t=self.task(actor,tid)
            if t['status'] not in ('available','planned','accepted','queued','rejected'):raise ValueError('После начала работы изменяйте приоритет или используйте переназначение с историей.')
            s,e=self._catalog_equipment(c,site,equipment,site_id,equipment_id)
            if worker_id:
                self._participants(c,worker_id,None);start=self._schedule(c,worker_id,day,start,duration,tid)
                if datetime.combine(date.fromisoformat(day),datetime.min.time())+timedelta(hours=start+duration)>moment(deadline):raise ValueError('Назначение выходит за срок.')
            changes={k:{'old':t[k],'new':v} for k,v in {'title':title.strip(),'description':description.strip(),'site':s['name'],'equipment':e['name'],'priority':priority,'kind':kind,'duration':duration,'day':day,'start':start if worker_id else None,'deadline':deadline,'worker_id':worker_id}.items() if t[k]!=v}
            changed_worker=t['worker_id']!=worker_id
            if changed_worker:self._assign(c,tid,actor,[worker_id] if worker_id else [],None,reason.strip())
            status=('planned' if worker_id else 'available') if changed_worker else t['status']
            c.execute('UPDATE tasks SET title=?,description=?,site=?,equipment=?,site_id=?,equipment_id=?,priority=?,kind=?,duration=?,day=?,start=?,deadline=?,worker_id=?,status=?,updated_at=? WHERE id=?',(title.strip(),description.strip(),s['name'],e['name'],s['id'],e['id'],priority,kind,duration,day,start if worker_id else None,deadline,worker_id,status,stamp(),tid))
            if changed_worker:c.execute('UPDATE tasks SET brigade_id=NULL,accepted_at=NULL,issued_at=?,assignment_version=assignment_version+1 WHERE id=?',(stamp(),tid))
            self.event(c,tid,actor['id'],'Исправлен наряд','edited',t['status'],status,reason.strip(),changes)

def defaultdict_list(rows,key,value):
    out={}
    for row in rows:out.setdefault(row[key],[]).append(row[value])
    return out
