"""Личный чат администратора: долговечная очередь без секретов в клиенте."""
import hmac,secrets,time,uuid


class AdminChat:
    def __init__(self,store,settings):
        self.store=store;self.settings=settings
        with store.transaction() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS chat_conversations(
                id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),created DOUBLE PRECISION NOT NULL);
            CREATE INDEX IF NOT EXISTS chat_owner ON chat_conversations(user_id,created);
            CREATE TABLE IF NOT EXISTS chat_requests(
                id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES chat_conversations(id),
                message TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,model TEXT NOT NULL DEFAULT '',created DOUBLE PRECISION NOT NULL,
                finished DOUBLE PRECISION,lease_token TEXT,lease_until DOUBLE PRECISION);
            CREATE INDEX IF NOT EXISTS chat_queue ON chat_requests(status,created);
            CREATE INDEX IF NOT EXISTS chat_history ON chat_requests(conversation_id,created);
            ''')
            if settings.database_url:
                for table in ('chat_conversations','chat_requests'):
                    c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                    c.execute(f'REVOKE ALL ON TABLE {table} FROM PUBLIC')
                    for role in ('anon','authenticated'):
                        if c.execute('SELECT rolname FROM pg_roles WHERE rolname=?',(role,)).fetchone():
                            c.execute(f'REVOKE ALL ON TABLE {table} FROM {role}')
            elif settings.ai_mode=='local':
                c.execute("UPDATE chat_requests SET status='queued',lease_token=NULL,lease_until=NULL WHERE status='processing'")

    @staticmethod
    def admin(user):
        if user['role'] not in ('master','manager','admin'):raise PermissionError('Чат с аналитикой доступен мастеру, руководителю и администратору.')

    def conversation(self,c,user,cid=''):
        self.admin(user)
        if cid:
            row=c.execute('SELECT id FROM chat_conversations WHERE id=? AND user_id=?',(cid,user['id'])).fetchone()
            if not row:raise PermissionError('Чат не найден или принадлежит другому администратору.')
        else:
            row=c.execute('SELECT id FROM chat_conversations WHERE user_id=? ORDER BY created DESC,id DESC LIMIT 1',(user['id'],)).fetchone()
            if not row:
                cid=uuid.uuid4().hex
                c.execute('INSERT INTO chat_conversations VALUES(?,?,?)',(cid,user['id'],time.time()))
                return cid
        return row['id']

    def online(self,c):
        if self.settings.ai_mode=='local':return True
        row=c.execute('SELECT last_seen FROM ai_worker_state WHERE id=1').fetchone()
        return bool(row and time.time()-row['last_seen']<45)

    def expire(self,c=None):
        if c is None:
            with self.store.transaction() as conn:return self.expire(conn)
        clock=time.time();online=self.online(c)
        for row in c.execute("SELECT * FROM chat_requests WHERE status IN ('queued','processing')").fetchall():
            error=''
            if not self.settings.ai_enabled:error='ИИ отключён на сервере. Включите AI_ENABLED и отправьте сообщение снова.'
            elif row['status']=='processing' and (row['lease_until'] or 0)<clock:error='Обработчик не ответил вовремя. Проверьте AnythingLLM и отправьте сообщение снова.'
            elif row['status']=='queued' and not online and clock-row['created']>=self.settings.offline_wait:error='ПК с ИИ не подключён. Запустите start_worker.bat и отправьте сообщение снова.'
            if error:
                c.execute("UPDATE chat_requests SET status='failed',error=?,finished=?,lease_token=NULL,lease_until=NULL WHERE id=?",(error,clock,row['id']))

    def history(self,user,cid=''):
        self.admin(user)
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.expire(c);cid=self.conversation(c,user,cid)
            rows=c.execute('SELECT id,message,answer,error,status,model,created FROM chat_requests WHERE conversation_id=? ORDER BY created DESC,id DESC LIMIT 100',(cid,)).fetchall()
            pending=c.execute("SELECT id FROM chat_requests WHERE conversation_id=? AND status IN ('queued','processing') LIMIT 1",(cid,)).fetchone()
            return {'conversation_id':cid,'messages':[dict(r) for r in reversed(rows)],
                    'ai_enabled':self.settings.ai_enabled,'online':self.online(c),'pending':bool(pending)}

    def new(self,user,request_id):
        self.admin(user)
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT user_id FROM chat_conversations WHERE id=?',(request_id,)).fetchone()
            if row and row['user_id']!=user['id']:raise PermissionError('Чат принадлежит другому администратору.')
            if not row:c.execute('INSERT INTO chat_conversations VALUES(?,?,?)',(request_id,user['id'],time.time()))
        return self.history(user,request_id)

    def send(self,user,cid,request_id,message):
        self.admin(user);message=message.strip()
        if not message or len(message)>4000:raise ValueError('Напишите сообщение длиной от 1 до 4000 символов.')
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.expire(c);cid=self.conversation(c,user,cid)
            previous=c.execute('SELECT conversation_id,message FROM chat_requests WHERE id=?',(request_id,)).fetchone()
            if previous:
                if previous['conversation_id']!=cid or previous['message']!=message:raise PermissionError('Идентификатор запроса уже использован.')
            else:
                if not self.settings.ai_enabled:raise ValueError('ИИ отключён. На Render установите AI_ENABLED=true.')
                if c.execute("SELECT id FROM chat_requests WHERE conversation_id=? AND status IN ('queued','processing')",(cid,)).fetchone():
                    raise ValueError('Дождитесь ответа на предыдущее сообщение.')
                c.execute('INSERT INTO chat_requests(id,conversation_id,message,status,created) VALUES(?,?,?,?,?)',(request_id,cid,message,'queued',time.time()))
        return self.history(user,cid)

    def claim(self):
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.expire(c)
            if not self.settings.ai_enabled:return None
            row=c.execute("SELECT r.*,u.id AS owner_id,u.role AS owner_role FROM chat_requests r JOIN chat_conversations t ON t.id=r.conversation_id JOIN users u ON u.id=t.user_id WHERE r.status='queued' AND u.active=1 AND u.role IN ('master','manager','admin') ORDER BY r.created,r.id LIMIT 1").fetchone()
            if not row:return None
            lease=secrets.token_urlsafe(32)
            c.execute("UPDATE chat_requests SET status='processing',lease_token=?,lease_until=? WHERE id=?",(lease,time.time()+660,row['id']))
            earlier=c.execute("SELECT message,answer FROM chat_requests WHERE conversation_id=? AND status='completed' AND created<? ORDER BY created DESC,id DESC LIMIT 6",(row['conversation_id'],row['created'])).fetchall()
            history=[];remaining=18000
            for old in earlier:
                size=len(old['message'])+len(old['answer'])
                if size>remaining:break
                history[0:0]=[{'role':'user','content':old['message']},{'role':'assistant','content':old['answer']}];remaining-=size
            facts=self.store.assistant_context({'id':row['owner_id'],'role':row['owner_role']})
            import json
            history.append({'role':'system','content':'READ_ONLY_DATABASE_FACTS: '+json.dumps(facts,ensure_ascii=False)})
            return {'kind':'chat','id':row['id'],'conversation_id':row['conversation_id'],'message':row['message'],'history':history,'lease':lease}

    def result(self,rid,lease,answer='',error='',model=''):
        if not isinstance(answer,str) or len(answer)>20000:raise ValueError('Некорректный ответ чата.')
        answer=answer.strip()
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.expire(c)
            row=c.execute('SELECT * FROM chat_requests WHERE id=?',(rid,)).fetchone()
            if not row:raise ValueError('Сообщение не найдено.')
            # Повтор доставки того же результата после сетевого обрыва безопасен.
            if row['status'] in ('completed','failed') and hmac.compare_digest(row['lease_token'] or '',lease):return
            if row['status']!='processing' or not hmac.compare_digest(row['lease_token'] or '',lease) or (row['lease_until'] or 0)<time.time():
                raise ValueError('Задание чата завершено либо срок обработки истёк.')
            c.execute('UPDATE chat_requests SET status=?,answer=?,error=?,model=?,finished=?,lease_until=NULL WHERE id=?',
                ('completed' if answer else 'failed',answer,'' if answer else (error or 'ИИ вернул пустой ответ.')[:1000],model[:200],time.time(),rid))
