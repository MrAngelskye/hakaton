"""Долговечная очередь: ИИ на домашнем ПК сам забирает задания по HTTPS."""
import hmac,json,secrets,time
from app.store import now

class RemoteJobs:
    def __init__(self,store,settings):
        self.store=store;self.settings=settings
        with store.transaction() as c:
            for col,kind in [('lease_token','TEXT'),('lease_until','DOUBLE PRECISION'),('queued_at','DOUBLE PRECISION')]:
                # PostgreSQL и SQLite для сетевых тестов поддерживают разные ADD COLUMN.
                if settings.database_url:c.execute(f'ALTER TABLE ai_jobs ADD COLUMN IF NOT EXISTS {col} {kind}')
                elif col not in [r['name'] for r in c.execute('PRAGMA table_info(ai_jobs)')]:c.execute(f'ALTER TABLE ai_jobs ADD COLUMN {col} {kind}')
            c.execute('CREATE TABLE IF NOT EXISTS ai_worker_state(id INTEGER PRIMARY KEY,last_seen DOUBLE PRECISION NOT NULL)')
            if settings.database_url:c.execute('ALTER TABLE ai_worker_state ENABLE ROW LEVEL SECURITY')
            c.execute('UPDATE ai_jobs SET queued_at=? WHERE queued_at IS NULL',(time.time(),))
    def heartbeat(self,c=None):
        if c is None:
            with self.store.transaction() as conn:return self.heartbeat(conn)
        c.execute('INSERT INTO ai_worker_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen',(time.time(),))
    def expire(self,c=None):
        if c is None:
            with self.store.transaction() as conn:return self.expire(conn)
        clock=time.time();state=c.execute('SELECT last_seen FROM ai_worker_state WHERE id=1').fetchone()
        offline=not state or clock-state['last_seen']>45
        for j in c.execute("SELECT report_id,status,lease_until,queued_at FROM ai_jobs WHERE status IN ('queued','processing')").fetchall():
            if j['status']=='processing' and (not self.settings.ai_enabled or (j['lease_until'] or 0)<clock):
                self.store.finish_ai(j['report_id'],None,'Обработчик ИИ не завершил проверку вовремя. Отчёт передан мастеру.',c=c)
            elif j['status']=='queued' and (not self.settings.ai_enabled or (offline and clock-(j['queued_at'] or clock)>=self.settings.offline_wait)):
                self.store.finish_ai(j['report_id'],None,'Обработчик ИИ выключен или не подключён. Отчёт передан мастеру.',c=c)
    def claim(self):
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.heartbeat(c);self.expire(c)
            j=c.execute("SELECT report_id FROM ai_jobs WHERE status='queued' ORDER BY report_id LIMIT 1").fetchone()
            if not j:return None
            rid=j['report_id'];lease=secrets.token_urlsafe(32)
            c.execute("UPDATE ai_jobs SET status='processing',lease_token=?,lease_until=? WHERE report_id=?",(lease,time.time()+660,rid))
            r=dict(c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone());t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(r['task_id'],)).fetchone())
            for field in ('materials','photos'):r[field]=json.loads(r[field])
            t,r=self.store.ai_context(c,t,r)
            return {'report':r,'task':t,'lease':lease}
    def require_lease(self,c,rid,lease):
        j=c.execute('SELECT * FROM ai_jobs WHERE report_id=?',(rid,)).fetchone()
        if not j or j['status']!='processing' or not hmac.compare_digest(j['lease_token'] or '',lease) or (j['lease_until'] or 0)<time.time():
            raise ValueError('Задание уже завершено либо срок обработки истёк.')
    def result(self,rid,lease,result,error,model):
        with self.store.transaction() as c:
            c.execute('BEGIN IMMEDIATE');self.require_lease(c,rid,lease);self.heartbeat(c)
            c.execute('UPDATE ai_jobs SET model=? WHERE report_id=?',(model,rid))
            self.store.finish_ai(rid,result,error,c=c)
            c.execute('UPDATE ai_jobs SET lease_token=NULL,lease_until=NULL WHERE report_id=?',(rid,))
