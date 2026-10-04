"""Deadline scheduler and retryable optional webhook delivery.

With no webhook configured, notifications are served by the authenticated inbox.
The webhook is an integration adapter; Android push requires a configured provider.
"""
import hashlib,hmac,json
from datetime import datetime,timedelta
from urllib.request import Request,urlopen
from app.case_store import stamp,moment,decoded

class NotificationDispatcher:
    def __init__(self,store,settings):self.store=store;self.settings=settings
    def tick(self):
        self.store.notification_tick()
        if not self.settings.notification_webhook:return
        clock=stamp()
        with self.store.transaction(write=True) as c:
            rows=[dict(r) for r in c.execute("SELECT * FROM notification_outbox WHERE attempts<8 AND next_attempt_at<=? AND (status IN ('pending','failed') OR (status='sending' AND lease_until<?)) ORDER BY id LIMIT 20",(clock,clock))]
            for row in rows:c.execute("UPDATE notification_outbox SET status='sending',attempts=attempts+1,lease_until=? WHERE id=?",((moment(clock)+timedelta(minutes=2)).isoformat(),row['id']))
        for row in rows:
            body=json.dumps({'id':row['id'],'event_key':row['event_key'],'user_id':row['user_id'],'task_id':row['task_id'],'kind':row['kind'],'payload':decoded(row['payload'],{})},ensure_ascii=False).encode()
            signature=hmac.new(self.settings.notification_webhook_key.encode(),body,hashlib.sha256).hexdigest()
            try:
                with urlopen(Request(self.settings.notification_webhook,data=body,headers={'Content-Type':'application/json','X-Naryadai-Signature':signature,'Idempotency-Key':row['event_key']}),timeout=8) as response:
                    if not 200<=response.status<300:raise OSError('HTTP delivery failed')
                with self.store.transaction(write=True) as c:c.execute("UPDATE notification_outbox SET status='sent',sent_at=?,lease_until=NULL,last_error='' WHERE id=?",(stamp(),row['id']))
            except Exception:
                delay=min(3600,5*2**(row['attempts']+1))
                with self.store.transaction(write=True) as c:c.execute("UPDATE notification_outbox SET status='failed',lease_until=NULL,last_error='Webhook unavailable',next_attempt_at=? WHERE id=?",((moment(stamp())+timedelta(seconds=delay)).isoformat(),row['id']))
