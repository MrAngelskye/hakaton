import json
from app.store import Store,now
from server.anythingllm import PROMPT_VERSION

class ServerStore(Store):
    def __init__(self,directory,settings):
        self.settings=settings
        super().__init__(directory)
        with self.transaction() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rpc_results(request_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,method TEXT NOT NULL,result TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_jobs(report_id INTEGER PRIMARY KEY REFERENCES reports(id),status TEXT NOT NULL,
              score INTEGER,verdict TEXT,summary TEXT,findings TEXT,criteria TEXT,error TEXT,model TEXT NOT NULL,prompt_version TEXT NOT NULL,
              created TEXT NOT NULL,finished TEXT);
            ''')
            # Сервер мог завершиться во время обработки: запрос вернётся в очередь.
            if settings.ai_mode=='local':c.execute("UPDATE ai_jobs SET status='queued' WHERE status='processing'")
            if not settings.ai_enabled:
                for j in c.execute("SELECT report_id FROM ai_jobs WHERE status='queued'").fetchall():
                    self.finish_ai(j['report_id'],None,'ИИ отключён в настройках сервера.',c=c)
    def initial_report_status(self,c):return 'aiPending' if self.settings.ai_enabled else 'submitted'
    def report_submitted(self,c,rid):
        c.execute('INSERT INTO ai_jobs(report_id,status,model,prompt_version,created) VALUES(?,?,?,?,?)',
            (rid,'queued' if self.settings.ai_enabled else 'skipped',self.settings.model_label,PROMPT_VERSION,now()))
        if self.settings.ai_mode=='remote_worker':
            import time
            c.execute('UPDATE ai_jobs SET queued_at=? WHERE report_id=?',(time.time(),rid))
    def reports(self,actor):
        rows=super().reports(actor)
        with self.transaction() as c:
            for r in rows:
                j=c.execute('SELECT * FROM ai_jobs WHERE report_id=?',(r['id'],)).fetchone()
                r['ai']=dict(j) if j else {'status':'skipped','error':'Отчёт создан до подключения ИИ.'}
                for k in ('findings','criteria'):
                    if r['ai'].get(k):r['ai'][k]=json.loads(r['ai'][k])
                for key in ('lease_token','lease_until','queued_at'):r['ai'].pop(key,None)
        return rows
    def take_ai_job(self):
        with self.transaction() as c:
            c.execute('BEGIN IMMEDIATE')
            j=c.execute("SELECT report_id FROM ai_jobs WHERE status='queued' ORDER BY report_id LIMIT 1").fetchone()
            if not j:return None
            rid=j['report_id'];c.execute("UPDATE ai_jobs SET status='processing' WHERE report_id=?",(rid,))
            r=dict(c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone())
            t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(r['task_id'],)).fetchone())
            r['materials']=json.loads(r['materials']);r['photos']=json.loads(r['photos'])
            return t,r
    def finish_ai(self,rid,result,error='',c=None):
        if c is None:
            with self.transaction() as conn:return self.finish_ai(rid,result,error,c=conn)
        r=c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone()
        if not r or r['status']!='aiPending':return
        status='completed' if result else 'failed'
        c.execute('UPDATE ai_jobs SET status=?,score=?,verdict=?,summary=?,findings=?,criteria=?,error=?,finished=? WHERE report_id=?',
            (status,result['score'] if result else None,result['verdict'] if result else None,result['summary'] if result else None,
             json.dumps(result['findings'],ensure_ascii=False) if result else None,json.dumps(result['criteria'],ensure_ascii=False) if result else None,
             error,now(),rid))
        c.execute("UPDATE reports SET status='submitted' WHERE id=?",(rid,))
        c.execute("UPDATE tasks SET status='submitted' WHERE id=? AND status='aiPending'",(r['task_id'],))
        actor=c.execute('SELECT master_id FROM tasks WHERE id=?',(r['task_id'],)).fetchone()[0]
        self.event(c,r['task_id'],actor,'Система: ИИ завершил предварительную проверку. Отчёт передан мастеру.' if result else 'Система: проверка ИИ недоступна. Отчёт передан мастеру для ручной проверки.')
