"""Persistent admin controls and audited commands. Never execute arbitrary SQL or shell."""
import hashlib,json,shlex,time,uuid
from datetime import date,timedelta
from app.case_store import stamp

HELP='''/help — команды
/status — база, ИИ, очередь
/events [число] — последние действия (1–100)
/tasks [статус] — последние наряды
/task НОМЕР — данные наряда
/users — сотрудники и роли
/ai on|off — включить/выключить ИИ
/web on|off — внешний поиск для технических вопросов
/pause НОМЕР причина — приостановить работу
/resume НОМЕР причина — возобновить
/cancel НОМЕР причина — отменить
/priority НОМЕР urgent|high|normal|scheduled причина
/user НОМЕР on|off — доступ сотрудника
/shift НОМЕР ГГГГ-ММ-ДД ЧЧ:ММ ЧЧ:ММ — смена
/announce сообщение — оповестить сотрудников
Изменения выполняются от вашего имени и записываются в журнал. SQL и команды Windows не исполняются.'''

class ControlCenter:
    def __init__(self,store,settings):
        self.store=store;self.settings=settings
        with store.transaction(write=True) as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS ai_worker_state(id INTEGER PRIMARY KEY,last_seen DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS service_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS support_audit(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS support_audit_time ON support_audit(created);
CREATE TABLE IF NOT EXISTS knowledge_documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,created_by INTEGER NOT NULL REFERENCES users(id),created TEXT NOT NULL);
''')
            if settings.database_url:
                if not c.execute("SELECT version FROM schema_migrations WHERE version='003'").fetchone():
                    from pathlib import Path
                    c.execute((Path(__file__).parent/'sql'/'manual_materials003.sql').read_text(encoding='utf-8'))
                for table in ('service_settings','support_audit','knowledge_documents','ai_worker_state'):
                    c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY');c.execute(f'REVOKE ALL ON TABLE {table} FROM PUBLIC')
                    for role in ('anon','authenticated'):
                        if c.execute('SELECT rolname FROM pg_roles WHERE rolname=?',(role,)).fetchone():c.execute(f'REVOKE ALL ON TABLE {table} FROM {role}')
        self.refresh()
    def refresh(self):
        with self.store.transaction() as c:
            row=c.execute("SELECT value FROM service_settings WHERE key='ai_enabled'").fetchone()
            if row:self.settings.ai_enabled=row['value']=='true'
    @staticmethod
    def admin(user):
        if user['role']!='admin':raise PermissionError('Раздел доступен только администратору.')
    def audit(self,c,user,action,detail):
        c.execute('INSERT INTO support_audit VALUES(?,?,?,?,?)',(uuid.uuid4().hex,user['id'],action,str(detail)[:2000],stamp()))
    def flag(self,c,key,default=False):
        row=c.execute('SELECT value FROM service_settings WHERE key=?',(key,)).fetchone();return row['value']=='true' if row else default
    def monitor(self,user):
        self.admin(user);self.refresh()
        with self.store.transaction() as c:
            last=c.execute('SELECT last_seen FROM ai_worker_state WHERE id=1').fetchone()
            counts={t:c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('users','tasks','reports','knowledge_documents')}
            queues={t:[dict(r) for r in c.execute('SELECT status,count(*) AS n FROM '+t+' GROUP BY status')] for t in ('ai_jobs','chat_requests')}
            jobs=[dict(r) for r in c.execute('SELECT report_id,status,error,model,created FROM ai_jobs ORDER BY report_id DESC LIMIT 20')]
            chats=[dict(r) for r in c.execute('SELECT id,status,error,model,created,finished FROM chat_requests ORDER BY created DESC LIMIT 20')]
            return {'database':'PostgreSQL' if self.settings.database_url else 'SQLite (локальная)', 'counts':counts,'ai_enabled':self.settings.ai_enabled,'web_enabled':self.flag(c,'web_enabled',True),'worker_online':self.settings.ai_mode=='local' or bool(last and time.time()-last['last_seen']<45),'last_seen':last['last_seen'] if last else None,'queues':queues,'report_jobs':jobs,'chat_jobs':chats,'events':self.events(user,50)}
    def events(self,user,limit=50):
        self.admin(user);limit=max(1,min(int(limit),100))
        with self.store.transaction() as c:
            actions=[dict(r) for r in c.execute('SELECT e.id,e.task_id,e.action,e.message,e.reason,e.created,u.name AS actor FROM events e LEFT JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT ?',(limit,))]
            support=[dict(r) for r in c.execute('SELECT a.id,a.action,a.detail AS message,a.created,u.name AS actor FROM support_audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.created DESC LIMIT ?',(limit,))]
            return sorted(actions+support,key=lambda r:r['created'],reverse=True)[:limit]
    def documents(self,user):
        if user['role'] not in ('admin','master'):raise PermissionError('Нет доступа к документации.')
        with self.store.transaction() as c:return [dict(r) for r in c.execute('SELECT id,title,created,length(body) AS size FROM knowledge_documents ORDER BY created DESC')]
    def put_document(self,user,title,body,request_id):
        self.admin(user);title=title.strip();body=body.strip()
        if not 2<=len(title)<=200 or not 20<=len(body)<=100000:raise ValueError('Название: 2–200 символов; документ: 20–100000 символов.')
        with self.store.transaction(write=True) as c:
            old=c.execute('SELECT title,body FROM knowledge_documents WHERE id=?',(request_id,)).fetchone()
            if old:
                if old['title']!=title or old['body']!=body:raise ValueError('Идентификатор уже использован другим документом.')
                return {'id':request_id}
            if c.execute('SELECT count(*) AS n FROM knowledge_documents').fetchone()['n']>=100:raise ValueError('В прототипе максимум 100 документов.')
            c.execute('INSERT INTO knowledge_documents VALUES(?,?,?,?,?)',(request_id,title,body,user['id'],stamp()));self.audit(c,user,'document_added',title)
        return {'id':request_id}
    def command(self,user,command,request_id):
        self.admin(user)
        if not command.strip() or len(command)>2000:raise ValueError('Команда: 1–2000 символов.')
        try:args=shlex.split(command)
        except ValueError:raise ValueError('Проверьте кавычки в команде.') from None
        name=args[0].lower();args=args[1:];digest=hashlib.sha256(command.encode()).hexdigest()
        with self.store.transaction(write=True) as c:
            old=c.execute('SELECT * FROM rpc_results WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['user_id']!=user['id'] or old['method']!='console' or old['payload_hash']!=digest:raise PermissionError('Идентификатор команды уже использован.')
                return json.loads(old['result'])
            try:
                if name=='/help' and not args:result=HELP
                elif name=='/status' and not args:result=self.monitor(user)
                elif name=='/events' and len(args)<=1:result=self.events(user,int(args[0]) if args else 30)
                elif name=='/users' and not args:result=self.store.users(user)
                elif name=='/tasks' and len(args)<=1:result=[{k:t.get(k) for k in ('id','title','status','worker_name','deadline')} for t in self.store.tasks(user,limit=100) if not args or t['status']==args[0]][:30]
                elif name=='/task' and len(args)==1:result=self.store.task(user,int(args[0]))
                elif name in ('/ai','/web') and len(args)==1 and args[0] in ('on','off'):
                    key='ai_enabled' if name=='/ai' else 'web_enabled';value=args[0]=='on'
                    c.execute('INSERT INTO service_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,'true' if value else 'false'));result={'setting':key,'enabled':value}
                elif name in ('/pause','/resume','/cancel') and len(args)>=2:
                    self.store.transition(user,int(args[0]),{'/pause':'paused','/resume':'inProgress','/cancel':'cancelled'}[name],' '.join(args[1:]));result='Статус наряда изменён.'
                elif name=='/priority' and len(args)>=3:
                    self.store.change_priority(user,int(args[0]),args[1],' '.join(args[2:]));result='Приоритет изменён.'
                elif name=='/user' and len(args)==2 and args[1] in ('on','off'):
                    self.store.set_active(user,int(args[0]),args[1]=='on');
                    if args[1]=='off':c.execute('DELETE FROM sessions WHERE user_id=?',(int(args[0]),))
                    result='Доступ сотрудника изменён.'
                elif name=='/shift' and len(args)==4:
                    def hour(v):
                        a,b=map(int,v.split(':'))
                        if not 0<=a<=23 or not 0<=b<=59:raise ValueError('Часы: 00:00–23:59.')
                        return a+b/60
                    self.store.set_shift(user,int(args[0]),args[1],hour(args[2]),hour(args[3]));result='Смена сохранена.'
                elif name=='/announce' and args:result=self.store.send_announcement(user,'Сообщение администратора',' '.join(args))
                else:raise ValueError('Неизвестная команда или параметры. Введите /help.')
            except (IndexError,TypeError):raise ValueError('Проверьте параметры: /help.') from None
            out={'output':result};self.audit(c,user,'console',command)
            c.execute('INSERT INTO rpc_results(request_id,user_id,method,result,created,payload_hash) VALUES(?,?,?,?,?,?)',(request_id,user['id'],'console',json.dumps(out,ensure_ascii=False),str(time.time()),digest))
        self.refresh();return out
