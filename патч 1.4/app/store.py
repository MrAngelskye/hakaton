"""Локальное хранилище. Все проверки доступа и переходы — здесь, не в UI."""
import csv
import hashlib
import hmac
import json
import math
import secrets
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

STATUS = {'available':'Выдан без исполнителя', 'planned':'Выдан', 'accepted':'Принят в работу', 'queued':'В очереди', 'rejected':'Отклонён', 'inProgress':'В работе',
          'aiPending':'Проверяет ИИ',
          'paused':'Приостановлен', 'submitted':'На проверке', 'approved':'Закрыт',
          'revision':'Доработка', 'cancelled':'Отменён', 'superseded':'Предыдущая версия'}
ROLES = {'worker':'Сотрудник', 'master':'Мастер', 'admin':'Администратор','manager':'Руководитель'}
SITES = ['Карьер','Дробильно-сортировочный комплекс','Обогатительная фабрика','Ремонтно-механический цех']
EMPLOYEE_STATUS = {'free':('Свободен','employeeGreen'), 'busy':('В работе','employeeYellow'),
                   'queued':('Есть в очереди','employeeBlue'), 'off':('Не на смене','employeeGray')}


def now():
    from app.case_store import stamp
    return stamp()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()


class LegacyStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.photos = self.directory / 'photos'
        self.photos.mkdir(exist_ok=True)
        self.path = self.directory / 'naryadai.db'
        with self.transaction() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
              name TEXT NOT NULL, job TEXT NOT NULL, role TEXT NOT NULL,
              salt TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS tasks(
              id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
              description TEXT NOT NULL, site TEXT NOT NULL, equipment TEXT NOT NULL,
              priority TEXT NOT NULL, kind TEXT NOT NULL, duration REAL NOT NULL,
              day TEXT NOT NULL, start REAL, deadline TEXT NOT NULL,
              worker_id INTEGER REFERENCES users(id), master_id INTEGER NOT NULL REFERENCES users(id),
              status TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id),
              worker_id INTEGER NOT NULL REFERENCES users(id), work TEXT NOT NULL,
              result TEXT NOT NULL, defect TEXT NOT NULL, hours REAL NOT NULL,
              materials TEXT NOT NULL, photos TEXT NOT NULL, status TEXT NOT NULL,
              score INTEGER, comment TEXT NOT NULL DEFAULT '', reviewer_id INTEGER REFERENCES users(id),
              created TEXT NOT NULL, reviewed TEXT);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id),
              actor_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS report_task ON reports(task_id);
            CREATE TABLE IF NOT EXISTS shift_rules(
              worker_id INTEGER NOT NULL REFERENCES users(id), weekday INTEGER NOT NULL,
              start REAL NOT NULL, end REAL NOT NULL, PRIMARY KEY(worker_id,weekday));
            CREATE TABLE IF NOT EXISTS shifts(
              worker_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
              start REAL, end REAL, updated_by INTEGER REFERENCES users(id), updated TEXT,
              PRIMARY KEY(worker_id,day));
            CREATE TABLE IF NOT EXISTS pauses(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id),
              actor_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
              started TEXT NOT NULL, ended TEXT, ended_by INTEGER REFERENCES users(id));
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_pause ON pauses(task_id) WHERE ended IS NULL;
            ''')
        self.migrate_case()
        self.seed()
        self.migrate_schedules()

    def migrate_schedules(self):
        # Идемпотентное обновление 1.1: существующие наряды и фото сохраняются.
        with self.transaction() as c:
            for u in c.execute("SELECT id FROM users WHERE role='worker'").fetchall() if getattr(self,'seed_demo',False) else ():
                for weekday in range(7):
                    c.execute('INSERT OR IGNORE INTO shift_rules VALUES(?,?,8,18)',(u['id'],weekday))
            for t in c.execute("SELECT id FROM tasks WHERE status='paused'").fetchall():
                if not c.execute('SELECT 1 FROM pauses WHERE task_id=? AND ended IS NULL',(t['id'],)).fetchone():
                    c.execute("INSERT INTO pauses(task_id,actor_id,reason,started) VALUES(?,(SELECT master_id FROM tasks WHERE id=?),?,?)",
                              (t['id'],t['id'],'Пауза из версии 1.1: причина не была указана',now()))

    @staticmethod
    def _shift(c,wid,day):
        override=c.execute('SELECT start,end FROM shifts WHERE worker_id=? AND day=?',(wid,day)).fetchone()
        if override is not None:return dict(override) if override['start'] is not None else None
        r=c.execute('SELECT start,end FROM shift_rules WHERE worker_id=? AND weekday=?',
                    (wid,date.fromisoformat(day).weekday())).fetchone()
        return dict(r) if r else None

    def shift(self,actor,wid,day):
        date.fromisoformat(day)
        with self.transaction() as c:
            u=self.require(c,actor)
            if u['role']=='worker' and u['id']!=wid:raise PermissionError('Доступен только собственный график.')
            return self._shift(c,wid,day)

    def set_shift(self,actor,wid,day,start=None,end=None):
        date.fromisoformat(day)
        if (start is None)!=(end is None) or (start is not None and
            (not all(math.isfinite(v) for v in (start,end)) or not 0<=start<end<24)):
            raise ValueError('Выберите начало и конец смены в пределах одного дня.')
        with self.transaction() as c:
            self.require(c,actor,('master','admin'));c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1",(wid,)).fetchone():
                raise ValueError('Выберите действующего сотрудника.')
            tasks=c.execute("SELECT * FROM tasks WHERE worker_id=? AND day=? AND status!='cancelled' AND start IS NOT NULL",(wid,day)).fetchall()
            if any(start is None or t['start']<start or t['start']+t['duration']>end for t in tasks):
                raise ValueError('Новая смена исключает назначенные работы. Сначала перенесите или отмените наряды.')
            c.execute('INSERT INTO shifts VALUES(?,?,?,?,?,?) ON CONFLICT(worker_id,day) DO UPDATE SET start=excluded.start,end=excluded.end,updated_by=excluded.updated_by,updated=excluded.updated',
                      (wid,day,start,end,actor['id'],now()))

    def free_slots(self,actor,wid,day,at=None):
        at=at or datetime.now();shift=self.shift(actor,wid,day)
        if not shift or date.fromisoformat(day)<at.date():return []
        with self.transaction() as c:
            tasks=c.execute("SELECT start,duration,status FROM tasks WHERE worker_id=? AND day=? AND status!='cancelled' AND start IS NOT NULL ORDER BY start",(wid,day)).fetchall()
        cursor=shift['start']
        if day==at.date().isoformat():
            # Следующая пятиминутка; продолжающаяся работа удерживает время до завершения.
            cursor=max(cursor,math.ceil((at.hour*60+at.minute+at.second/60)/5)*5/60)
            if any(t['status'] in ('inProgress','paused') and t['start']+t['duration']<=cursor for t in tasks):return []
        result=[]
        for t in tasks:
            if t['start']>cursor:result.append((cursor,min(t['start'],shift['end'])))
            cursor=max(cursor,t['start']+t['duration'])
        if cursor<shift['end']:result.append((cursor,shift['end']))
        return [(a,b) for a,b in result if b-a>=.5-1e-8]

    def employee_status(self,actor,wid,at=None):
        at=at or datetime.now();day=at.date().isoformat();shift=self.shift(actor,wid,day)
        hour=at.hour+at.minute/60+at.second/3600
        active=next((u for u in self.users(actor,True) if u['id']==wid),None)
        if not active or not active['active'] or not shift or not shift['start']<=hour<shift['end']:return 'off'
        tasks=[t for t in self.tasks(actor) if t['worker_id']==wid]
        if any(t['status'] in ('inProgress','paused') or (t['day']==day and t['start'] is not None and t['start']<=hour<t['start']+t['duration'] and t['status']=='planned') for t in tasks):return 'busy'
        if any(t['status'] in ('planned','revision') for t in tasks):return 'queued'
        return 'free'

    def pauses(self,actor,tid):
        self.task(actor,tid)
        with self.transaction() as c:
            return [dict(r) for r in c.execute('SELECT * FROM pauses WHERE task_id=? ORDER BY id',(tid,))]

    @contextmanager
    def transaction(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def require(c, actor, roles=None):
        u = c.execute('SELECT * FROM users WHERE id=? AND active=1', (actor['id'],)).fetchone()
        if not u or (roles and u['role'] not in roles):
            raise PermissionError('Недостаточно прав для этого действия.')
        return dict(u)

    def event(self, c, task_id, actor_id, message):
        c.execute('INSERT INTO events(task_id,actor_id,message,created) VALUES(?,?,?,?)',
                  (task_id, actor_id, message, now()))

    def seed(self):
        with self.transaction() as c:
            if c.execute('SELECT count(*) FROM users').fetchone()[0]:
                return
            for username,name,job,role in [
                ('master','Мария Соколова','Мастер смены','master'),
                ('worker1','Александр Иванов','Механик · сборочный цех','worker'),
                ('worker2','Данияр Ахметов','Электрик · сборочный цех','worker'),
                ('worker3','Елена Ким','Наладчик · сварочный цех','worker'),
                ('worker4','Руслан Омаров','Механик · окрасочный цех','worker'),
                ('admin','Администратор','Управление доступом','admin')]:
                salt=secrets.token_hex(16)
                c.execute('INSERT INTO users(username,name,job,role,salt,password_hash) VALUES(?,?,?,?,?,?)',
                          (username,name,job,role,salt,password_hash(getattr(self,'seed_password','1234'),salt)))
            today = date.today()
            samples=[
                (1048,'Проверить привод сборочного конвейера',0,'Конвейер СЛ-03',2,'urgent',None,'available',None),
                (1049,'Проверить динамометрический инструмент',0,'Пост сборки №12',1,'normal',None,'available',None),
                (1050,'Обслужить маркировочный принтер',3,'Принтер МП-07',1.5,'normal',None,'available',None),
                (1051,'Осмотреть пневматическую линию',1,'Пневмолиния ПЛ-02',1,'normal',None,'available',None),
                (1052,'Устранить сбой сканера VIN',3,'Сканер СК-04',1,'urgent',None,'available',None),
                (1046,'Осмотреть ролики конвейера',0,'Конвейер СЛ-01',1.5,'normal',2,'planned',8),
                (1047,'Проверить датчик на посту сборки',0,'Пост сборки №08',1,'normal',2,'inProgress',10),
                (1044,'Обслужить привод сварочного стенда',1,'Стенд СВ-02',1.5,'normal',4,'submitted',8),
                (1045,'Проверить блок считывания маркировки',0,'Пост сборки №15',1,'normal',3,'submitted',9),
            ]
            for tid,title,site,equipment,duration,priority,wid,status,start in samples:
                c.execute('''INSERT INTO tasks(id,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,master_id,status,created)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (tid,title,'Проверить состояние оборудования, устранить замечания и записать результаты контрольной проверки.',
                           SITES[site],equipment,priority,'Внеплановая' if priority=='urgent' else 'Плановая',duration,
                           today.isoformat(),start,f'{today}T18:00',wid,1,status,now()))
                self.event(c,tid,1,'Создан демонстрационный наряд')
                if status=='submitted':
                    self._seed_report(c,tid,wid,duration,'submitted',None)
            for i,(wid,score) in enumerate([(2,94),(2,91),(3,92),(3,95),(4,98),(4,95),(5,89),(5,93)]):
                tid=1030+i
                day=(today-timedelta(days=1+i%3)).isoformat()
                c.execute('''INSERT INTO tasks(id,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,master_id,status,created)
                             VALUES(?,?,?,?,?,'normal','Плановая',1,?,8,?,?,1,'approved',?)''',
                          (tid,['Осмотр электропривода','Проверка датчиков линии','Обслуживание поста'][i%3],
                           'Провести плановый осмотр.',SITES[i%4],f'Пост №{i+1}',day,day+'T18:00',wid,now()))
                self._seed_report(c,tid,wid,1,'approved',score)
                self.event(c,tid,1,'Работа принята мастером (демонстрационные данные)')

    def _seed_report(self,c,tid,wid,hours,status,score):
        c.execute('''INSERT INTO reports(task_id,worker_id,work,result,defect,hours,materials,photos,status,score,comment,reviewer_id,created,reviewed)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (tid,wid,'Выполнен плановый осмотр. Очищены контакты, проверены крепления.',
                   'Контрольная проверка пройдена, оборудование работает штатно.','D-03 · Загрязнение',hours,
                   json.dumps([{'name':'Салфетки','quantity':2,'unit':'шт.','price':50}],ensure_ascii=False),'[]',
                   status,score,'Работа принята. Результаты описаны понятно.' if score is not None else '',
                   1 if score is not None else None,
                   c.execute('SELECT day FROM tasks WHERE id=?',(tid,)).fetchone()[0]+'T16:00:00' if score is not None else now(),
                   c.execute('SELECT day FROM tasks WHERE id=?',(tid,)).fetchone()[0]+'T17:00:00' if score is not None else None))

    def authenticate(self,username,password,role):
        with self.transaction() as c:
            u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(username.strip(),)).fetchone()
        if not u or u['role']!=role or not hmac.compare_digest(u['password_hash'],password_hash(password,u['salt'])):
            raise ValueError('Проверьте логин, пароль и выбранную роль.')
        return {k:u[k] for k in ('id','username','name','job','role','active')}

    def users(self,actor,workers_only=False):
        with self.transaction() as c:
            self.require(c,actor)
            q="SELECT id,username,name,job,role,active FROM users"
            q += " WHERE role='worker'" if workers_only else ''
            return [dict(r) for r in c.execute(q+' ORDER BY name')]

    def tasks(self,actor):
        with self.transaction() as c:
            u=self.require(c,actor)
            q='''SELECT t.*,u.name AS worker_name FROM tasks t LEFT JOIN users u ON u.id=t.worker_id'''
            args=()
            if u['role']=='worker':
                q+=' WHERE t.worker_id=? OR (t.worker_id IS NULL AND t.status=\'available\')'
                args=(u['id'],)
            return [dict(r) for r in c.execute(q+' ORDER BY t.id DESC',args)]

    def task(self,actor,tid):
        items=[t for t in self.tasks(actor) if t['id']==tid]
        if not items: raise PermissionError('Наряд не найден или недоступен.')
        return items[0]

    def create_task(self,actor,*,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id=None):
        if len(title.strip())<5 or len(description.strip())<10 or not equipment.strip():
            raise ValueError('Заполните название (от 5 символов), описание (от 10) и оборудование.')
        if not math.isfinite(duration) or not .5<=duration<=10 or priority not in ('urgent','normal'):
            raise ValueError('Проверьте время и приоритет.')
        if site not in SITES or kind not in ('Плановая','Внеплановая'):
            raise ValueError('Проверьте участок и тип работ.')
        date.fromisoformat(day)
        due=datetime.fromisoformat(deadline)
        if due.date()<date.fromisoformat(day): raise ValueError('Срок не может быть раньше дня работ.')
        with self.transaction() as c:
            self.require(c,actor,('master','admin'))
            c.execute('BEGIN IMMEDIATE')
            if worker_id:
                if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1",(worker_id,)).fetchone():
                    raise ValueError('Выберите действующего сотрудника.')
                self._schedule(c,worker_id,day,start,duration)
                if due < datetime.fromisoformat(f'{day}T{int(start):02d}:{int(round(start%1*60)):02d}')+timedelta(hours=duration):
                    raise ValueError('Работа в графике заканчивается позже срока наряда.')
            cur=c.execute('''INSERT INTO tasks(title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,master_id,status,created)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (title.strip(),description.strip(),site,equipment.strip(),priority,kind,duration,day,
                           start if worker_id else None,deadline,worker_id,actor['id'],'planned' if worker_id else 'available',now()))
            self.event(c,cur.lastrowid,actor['id'],'Наряд создан'+(' и назначен сотруднику' if worker_id else ' в общем списке'))
            return cur.lastrowid

    @staticmethod
    def _schedule(c,wid,day,start,duration,exclude=-1):
        shift=Store._shift(c,wid,day)
        if not shift:raise ValueError('На этот день сотрудник не на смене. Мастер должен настроить график.')
        if start is None or not math.isfinite(start) or start<shift['start'] or start+duration>shift['end']:
            raise ValueError('Работа должна полностью помещаться в смену сотрудника.')
        if c.execute("""SELECT 1 FROM tasks WHERE worker_id=? AND day=? AND id!=?
                        AND status!='cancelled' AND start IS NOT NULL AND start<? AND start+duration>?""",
                     (wid,day,exclude,start+duration,start)).fetchone():
            raise ValueError('На это время уже запланирован другой наряд.')

    def claim(self,actor,tid,day,start):
        with self.transaction() as c:
            self.require(c,actor,('worker',))
            c.execute('BEGIN IMMEDIATE')
            t=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t or t['status']!='available' or t['worker_id'] is not None:
                raise ValueError('Этот наряд уже назначен.')
            date.fromisoformat(day)
            self._schedule(c,actor['id'],day,start,t['duration'],tid)
            end=datetime.fromisoformat(f'{day}T{int(start):02d}:{int(round(start%1*60)):02d}')+timedelta(hours=t['duration'])
            if end>datetime.fromisoformat(t['deadline']): raise ValueError('Выбранное время выходит за срок наряда.')
            c.execute("UPDATE tasks SET worker_id=?,day=?,start=?,status='planned' WHERE id=?",(actor['id'],day,start,tid))
            self.event(c,tid,actor['id'],'Наряд добавлен в график')

    def reschedule(self,actor,tid,day,start):
        with self.transaction() as c:
            u=self.require(c,actor,('worker','master','admin'))
            c.execute('BEGIN IMMEDIATE')
            t=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t or t['worker_id'] is None or (u['role']=='worker' and t['worker_id']!=u['id']): raise PermissionError('Наряд другого сотрудника.')
            if t['status']!='planned': raise ValueError('Перенести можно только запланированный наряд.')
            date.fromisoformat(day)
            self._schedule(c,t['worker_id'],day,start,t['duration'],tid)
            end=datetime.fromisoformat(f'{day}T{int(start):02d}:{int(round(start%1*60)):02d}')+timedelta(hours=t['duration'])
            if end>datetime.fromisoformat(t['deadline']): raise ValueError('Выбранное время выходит за срок наряда.')
            c.execute('UPDATE tasks SET day=?,start=? WHERE id=?',(day,start,tid))
            self.event(c,tid,actor['id'],'Изменено время в графике')

    def transition(self,actor,tid,status,reason=''):
        allowed={'planned':{'inProgress'},'inProgress':{'paused'},'paused':{'inProgress'}}
        with self.transaction() as c:
            u=self.require(c,actor)
            c.execute('BEGIN IMMEDIATE')
            t=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t: raise ValueError('Наряд не найден.')
            if status=='cancelled':
                self.require(c,actor,('master','admin'))
                if t['status'] not in ('available','planned','inProgress','paused','revision'):
                    raise ValueError('Этот наряд нельзя отменить.')
                # Возвращённые отчёты перестают числиться требующими действий.
                c.execute("UPDATE reports SET status='cancelled' WHERE task_id=? AND status='revision'",(tid,))
            else:
                u=self.require(c,actor,('worker','admin'))
                if t['worker_id'] is None or (u['role']!='admin' and t['worker_id']!=u['id']): raise PermissionError('Наряд другого сотрудника.')
                if status not in allowed.get(t['status'],set()): raise ValueError('Действие недоступно в текущем статусе.')
            if status=='paused':
                reason=reason.strip()
                if not 3<=len(reason)<=1000:raise ValueError('Укажите причину паузы: от 3 до 1000 символов.')
                c.execute('INSERT INTO pauses(task_id,actor_id,reason,started) VALUES(?,?,?,?)',(tid,actor['id'],reason,now()))
            if t['status']=='paused':
                c.execute('UPDATE pauses SET ended=?,ended_by=? WHERE task_id=? AND ended IS NULL',(now(),actor['id'],tid))
            c.execute('UPDATE tasks SET status=? WHERE id=?',(status,tid))
            self.event(c,tid,actor['id'],STATUS[status]+(': '+reason if status=='paused' else ''))

    def reports(self,actor):
        with self.transaction() as c:
            u=self.require(c,actor)
            q='''SELECT r.*,t.title,t.site,t.equipment,u.name AS worker_name,v.name AS reviewer_name
                 FROM reports r JOIN tasks t ON t.id=r.task_id JOIN users u ON u.id=r.worker_id
                 LEFT JOIN users v ON v.id=r.reviewer_id'''
            args=()
            if u['role']=='worker': q+=' WHERE r.worker_id=?'; args=(u['id'],)
            rows=[dict(r) for r in c.execute(q+' ORDER BY r.id DESC',args)]
            for r in rows:
                r['materials']=json.loads(r['materials']);r['photos']=json.loads(r['photos'])
            return rows

    def latest_report(self,actor,tid):
        return next((r for r in self.reports(actor) if r['task_id']==tid),None)

    def submit(self,actor,tid,*,work,result,defect,hours,materials,photo_sources):
        if len(work.strip())<10 or len(result.strip())<3:
            raise ValueError('Опишите работы (от 10 символов) и результат (от 3 символов).')
        if not math.isfinite(hours) or not .1<=hours<=24: raise ValueError('Укажите фактическое время от 0,1 до 24 часов.')
        for m in materials:
            if not m['name'].strip() or not all(math.isfinite(float(m[k])) for k in ('quantity','price')) or float(m['quantity'])<=0 or float(m['price'])<0:
                raise ValueError('Материал: название, положительное количество и цена от 0.')
            if not m['unit'].strip(): raise ValueError('Укажите единицу измерения материала.')
        if len(photo_sources)>3: raise ValueError('Можно приложить до 3 фотографий.')
        copied=[]
        try:
            with self.transaction() as c:
                u=self.require(c,actor,('worker','admin'))
                c.execute('BEGIN IMMEDIATE')
                t=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
                if not t or t['worker_id'] is None or (u['role']!='admin' and t['worker_id']!=u['id']): raise PermissionError('Нет доступа к этому наряду.')
                if t['status'] not in ('inProgress','revision'): raise ValueError('Отчёт сейчас нельзя отправить.')
                stored=[]
                for src in photo_sources:
                    p=Path(src)
                    if not p.is_file() or p.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or p.stat().st_size>8*1024*1024:
                        raise ValueError('Фото: JPG, PNG или WebP до 8 МБ.')
                    # Серверу не нужен графический Qt: та же проверка через Pillow.
                    from PIL import Image
                    try:
                        with Image.open(p) as image:
                            if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>40_000_000:
                                raise ValueError('Неподдерживаемый формат или размер фото.')
                            image.verify()
                        with Image.open(p) as image:image.load()
                    except (OSError,ValueError,Image.DecompressionBombError):
                        raise ValueError('Файл не является поддерживаемой фотографией (до 40 Мп).') from None
                    target=self.save_photo(p)
                    copied.append(target);stored.append(target.name)
                c.execute("UPDATE reports SET status='superseded' WHERE task_id=? AND status='revision'",(tid,))
                status=self.initial_report_status(c)
                cur=c.execute('''INSERT INTO reports(task_id,worker_id,work,result,defect,hours,materials,photos,status,created)
                                 VALUES(?,?,?,?,?,?,?,?,?,?)''',
                              (tid,t['worker_id'],work.strip(),result.strip(),defect,hours,json.dumps(materials,ensure_ascii=False),json.dumps(stored),status,now()))
                c.execute('UPDATE tasks SET status=? WHERE id=?',(status,tid))
                self.report_submitted(c,cur.lastrowid)
                self.event(c,tid,actor['id'],f'Отправлен отчёт ОТ-{cur.lastrowid:04d}'+(' на предварительную проверку ИИ' if status=='aiPending' else ' мастеру'))
                return cur.lastrowid
        except Exception:
            for p in copied:
                try:self.remove_photo(p)
                except OSError:pass  # Первоначальная ошибка важнее; недоступное хранилище проверят отдельно.
            raise

    def initial_report_status(self,c):return 'submitted'
    def report_submitted(self,c,rid):pass

    def save_photo(self,p):
        target=self.photos/(uuid.uuid4().hex+p.suffix.lower());shutil.copy2(p,target);return target
    def remove_photo(self,p):p.unlink(missing_ok=True)
    def read_photo(self,name):
        if name.startswith('demo_'):
            from server.demo_import import read_demo_photo
            return read_demo_photo(name)
        return (self.photos/name).read_bytes()

    def review(self,actor,rid,approve,score,comment):
        if len(comment.strip())<3: raise ValueError('Добавьте комментарий от 3 символов.')
        if approve and (not isinstance(score,int) or not 0<=score<=100): raise ValueError('Оценка должна быть от 0 до 100.')
        with self.transaction() as c:
            self.require(c,actor,('master','admin'))
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone()
            if not r or r['status']!='submitted': raise ValueError('Этот отчёт уже проверен или отсутствует.')
            t=c.execute('SELECT * FROM tasks WHERE id=?',(r['task_id'],)).fetchone()
            if t['status']!='submitted': raise ValueError('Статус наряда изменился.')
            status='approved' if approve else 'revision'
            c.execute('UPDATE reports SET status=?,score=?,comment=?,reviewer_id=?,reviewed=? WHERE id=?',
                      (status,score if approve else None,comment.strip(),actor['id'],now(),rid))
            c.execute('UPDATE tasks SET status=? WHERE id=?',(status,r['task_id']))
            self.event(c,r['task_id'],actor['id'],('Работа принята' if approve else 'Возврат на доработку')+': '+comment.strip())

    def events(self,actor,tid):
        self.task(actor,tid)
        with self.transaction() as c:
            return [dict(r) for r in c.execute('''SELECT e.*,u.name FROM events e JOIN users u ON u.id=e.actor_id
                                                WHERE task_id=? ORDER BY e.id''',(tid,))]

    def metrics(self,actor):
        tasks=self.tasks(actor);reports=self.reports(actor)
        people=self.users(actor,True)
        out=[]
        for u in people:
            rr=[r for r in reports if r['worker_id']==u['id'] and r['status']=='approved']
            out.append({**u,'employee_status':self.employee_status(actor,u['id']),'done':len(rr),'score':sum(r['score'] for r in rr)/len(rr) if rr else None,
                        'hours':sum(r['hours'] for r in rr),
                        'active_count':sum(t['worker_id']==u['id'] and t['status'] not in ('approved','cancelled') for t in tasks)})
        return sorted(out,key=lambda u:u['score'] if u['score'] is not None else -1,reverse=True)

    def add_user(self,actor,username,name,job,role,password):
        minimum=4 if getattr(self,'seed_demo',False) else 12
        if not username.strip() or len(username.strip())>100 or len(name.strip())<3 or (not getattr(self,'seed_demo',False) and not job.strip()) or len(password)<minimum or len(password)>300 or role not in ROLES:
            raise ValueError(f'Заполните логин (до 100 символов), имя, должность и пароль ({minimum}–300 символов).')
        salt=secrets.token_hex(16)
        with self.transaction() as c:
            self.require(c,actor,('admin',))
            try:
                c.execute('INSERT INTO users(username,name,job,role,salt,password_hash) VALUES(?,?,?,?,?,?)',
                          (username.strip(),name.strip(),job.strip(),role,salt,password_hash(password,salt)))
                uid=c.execute('SELECT id FROM users WHERE username=?',(username.strip(),)).fetchone()[0]
                if role=='worker' and getattr(self,'seed_demo',False):
                    c.executemany('INSERT INTO shift_rules VALUES(?,?,8,18)',[(uid,d) for d in range(7)])
                if not getattr(self,'seed_demo',False):
                    from app.production_data import register_user_profile
                    register_user_profile(c,uid)
            except sqlite3.IntegrityError as e: raise ValueError('Этот логин уже занят.') from e

    def set_active(self,actor,uid,active):
        with self.transaction() as c:
            self.require(c,actor,('admin',))
            if uid==actor['id']: raise ValueError('Нельзя отключить собственный аккаунт.')
            if not active and c.execute("SELECT 1 FROM tasks WHERE worker_id=? AND status NOT IN ('approved','cancelled')",(uid,)).fetchone():
                raise ValueError('У сотрудника есть текущие наряды. Сначала завершите или отмените их.')
            c.execute('UPDATE users SET active=? WHERE id=?',(int(active),uid))

    def export_reports(self,actor,path):
        reports=self.reports(actor)
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f,delimiter=';')
            writer.writerow(['Отчёт','Наряд','Работа','Сотрудник','Статус','Часы','Оценка мастера','Материалы, тг','Комментарий','Дата'])
            for r in reports:
                values=[r['id'],r['task_id'],r['title'],r['worker_name'],STATUS[r['status']],r['hours'],r['score'],
                        round(sum(m['quantity']*m['price'] for m in r['materials']),2),r['comment'],r['created']]
                # Текст пользователя не должен превращаться в формулу Excel.
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in values])


    def reset_password(self,actor,uid,password):
        minimum=4 if getattr(self,'seed_demo',False) else 12
        if not minimum<=len(password)<=300:raise ValueError(f'Пароль должен содержать {minimum}–300 символов.')
        with self.transaction() as c:
            self.require(c,actor,('admin',))
            if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise ValueError('Пользователь не найден.')
            salt=secrets.token_hex(16)
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,password_hash(password,salt),uid))

    def support_update_task(self,actor,tid,*,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,reason):
        if len(reason.strip())<3:raise ValueError('Укажите причину исправления (от 3 символов).')
        if len(title.strip())<5 or len(description.strip())<10 or not equipment.strip():
            raise ValueError('Заполните название, описание и оборудование.')
        if not math.isfinite(duration) or not .5<=duration<=10 or priority not in ('urgent','normal'):
            raise ValueError('Проверьте плановое время и приоритет.')
        if site not in SITES or kind not in ('Плановая','Внеплановая'):raise ValueError('Проверьте участок и тип работ.')
        date.fromisoformat(day);due=datetime.fromisoformat(deadline)
        if due.date()<date.fromisoformat(day):raise ValueError('Срок не может быть раньше дня работ.')
        with self.transaction() as c:
            self.require(c,actor,('admin',));c.execute('BEGIN IMMEDIATE')
            t=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t or t['status'] not in ('available','planned','inProgress','paused','revision'):
                raise ValueError('Наряд на проверке или завершён. Исторические данные сохраняются; сначала примите решение по отчёту.')
            if t['status'] not in ('available','planned') and (worker_id!=t['worker_id'] or day!=t['day'] or start!=t['start'] or duration!=t['duration']):
                raise ValueError('У начатой задачи нельзя менять исполнителя или график. Можно исправить описание, срок и приоритет.')
            if worker_id:
                if not c.execute("SELECT 1 FROM users WHERE id=? AND role='worker' AND active=1",(worker_id,)).fetchone():
                    raise ValueError('Выберите действующего сотрудника.')
                self._schedule(c,worker_id,day,start,duration,tid)
                end=datetime.fromisoformat(f'{day}T{int(start):02d}:{int(round(start%1*60)):02d}')+timedelta(hours=duration)
                if end>due:raise ValueError('Время работы выходит за срок наряда.')
            else:start=None
            status=('planned' if worker_id else 'available') if t['status'] in ('available','planned') else t['status']
            values=dict(title=title.strip(),description=description.strip(),site=site,equipment=equipment.strip(),
                        priority=priority,kind=kind,duration=duration,day=day,start=start,deadline=deadline,worker_id=worker_id,status=status)
            changes={k:{'было':t[k],'стало':v} for k,v in values.items() if t[k]!=v}
            if not changes:raise ValueError('Нет изменений для сохранения.')
            c.execute('''UPDATE tasks SET title=?,description=?,site=?,equipment=?,priority=?,kind=?,duration=?,day=?,start=?,deadline=?,worker_id=?,status=? WHERE id=?''',
                      (*values.values(),tid))
            self.event(c,tid,actor['id'],'Исправление поддержкой: '+reason.strip()+'\n'+json.dumps(changes,ensure_ascii=False))



from app.case_store import CaseWorkflow

class Store(CaseWorkflow, LegacyStore):
    pass
