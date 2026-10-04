"""Сетевое хранилище для существующих экранов Qt."""
import base64,csv,hashlib,json,tempfile,uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse,quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from app.store import STATUS

class RemoteStore:
    is_remote=True
    def __init__(self,url,transport=None):
        self.url=url.rstrip('/');p=urlparse(self.url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment:raise ValueError('Укажите адрес сервера, например http://192.168.1.10:8000.')
        self.token='';self.actor=None;self._snapshot=None;self._day=date.today().isoformat();self.transport=transport;self._retry_requests={}
        health=self.request('/health',auth=False)
        if not isinstance(health,dict) or health.get('ok') is not True or 'version' not in health:raise ValueError('По этому адресу не найден сервер НарядAI.')
        self._cache=tempfile.TemporaryDirectory(prefix='naryadai-client-');self.photos=Path(self._cache.name)
    def request(self,path,payload=None,auth=True,binary=False):
        if self.transport:return self.transport(path,payload,self.token if auth else '',binary)
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.token
        req=Request(self.url+path,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,headers=headers,method='POST' if payload is not None else 'GET')
        try:
            with urlopen(req,timeout=8 if payload is None else 30) as r:
                data=r.read(36*1024*1024+1)
                if len(data)>36*1024*1024:raise OSError('Ответ сервера слишком большой.')
                return data if binary else json.loads(data)
        except HTTPError as e:
            try:message=json.loads(e.read()).get('detail','Сервер отклонил запрос.')
            except (ValueError,UnicodeError):message='Сервер отклонил запрос.'
            if not isinstance(message,str):message='Проверьте заполненные поля.'
            if e.code>=500:raise OSError('Сервер временно недоступен. Повторите то же действие после восстановления связи.') from None
            if e.code in (401,403):raise PermissionError(message) from None
            raise ValueError(message) from None
        except (URLError,TimeoutError,OSError):raise OSError('Нет связи с сервером. Проверьте интернет и адрес сервера. После простоя подключение может занять около минуты.') from None
        except (ValueError,UnicodeError):raise OSError('Сервер вернул неподдерживаемый ответ.') from None
    def authenticate(self,username,password,role):
        self.logout();r=self.request('/api/login',{'username':username,'password':password,'role':role},auth=False)
        self.token=r['token'];self.actor=r['user'];self._snapshot=None;return self.actor
    def logout(self):
        if self.token:
            try:self.request('/api/logout',{})
            except (OSError,ValueError,PermissionError):pass
        self.token='';self.actor=None;self._snapshot=None;self._retry_requests.clear()
        error=None
        for p in self.photos.glob('*'):
            try:p.unlink(missing_ok=True)
            except OSError as exc:error=exc
        if error:raise error
    def refresh_snapshot(self,day=None):
        self._day=day or self._day
        snap=self.request('/api/snapshot?day='+quote(self._day,safe=''))
        self._snapshot=snap
        return snap
    def snapshot(self):
        if self._snapshot is None:self.refresh_snapshot()
        return self._snapshot
    def call(self,method,*args,photos=None,**kwargs):
        data={'args':list(args),'kwargs':kwargs,'photos':photos or []}
        fingerprint=hashlib.sha256(json.dumps([method,data],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        body={**data,'request_id':self._retry_requests.get(fingerprint) or uuid.uuid4().hex}
        try:result=self.request('/api/call/'+method,body)['result']
        except OSError:
            self._retry_requests[fingerprint]=body['request_id']
            raise
        self._retry_requests.pop(fingerprint,None)
        if method not in ('task','events','pauses','shift','free_slots','employee_status','references','equipment_history','alerts','attention','notification_settings'):self._snapshot=None
        return result
    def tasks(self,actor):return self.snapshot()['tasks']
    def users(self,actor,workers_only=False):return [u for u in self.snapshot()['users'] if not workers_only or u['role']=='worker']
    def reports(self,actor):return self.snapshot()['reports']
    def task(self,actor,tid):
        self.refresh_snapshot()
        t=next((t for t in self.tasks(actor) if t['id']==tid),None)
        if t is None:raise PermissionError('Наряд не найден или недоступен.')
        return t
    def latest_report(self,actor,tid):return next((r for r in self.reports(actor) if r['task_id']==tid),None)
    def events(self,actor,tid):return self.call('events',tid)
    def pauses(self,actor,tid):return self.call('pauses',tid)
    def references(self,actor,category=None,site=None):
        data=self.snapshot().get('references')
        if data is not None and site is None:return data.get(category,[]) if category else data
        return self.call('references',category=category,site=site)
    def alerts(self,actor,at=None):
        if at is None:return self.snapshot().get('alerts',[])
        return self.call('alerts',at=at)
    def attention(self,actor,at=None):
        if at is None:return self.snapshot().get('attention',{})
        return self.call('attention',at=at)
    def equipment_history(self,actor,equipment):return self.call('equipment_history',equipment)
    def notification_settings(self,actor):return self.call('notification_settings')
    def shift(self,actor,wid,day):
        s=self.snapshot()
        if day==s['day'] and str(wid) in s['shifts']:return s['shifts'][str(wid)]
        return self.call('shift',wid,day)
    def free_slots(self,actor,wid,day,at=None):
        s=self.snapshot()
        if at is None and day==s['day'] and str(wid) in s['free_slots']:return s['free_slots'][str(wid)]
        return self.call('free_slots',wid,day)
    def employee_status(self,actor,wid,at=None):return self.snapshot()['employee_status'].get(str(wid),'off')
    def metrics(self,actor):
        tasks=self.tasks(actor);reports=self.reports(actor);out=[]
        for u in self.users(actor,True):
            rr=[r for r in reports if r['worker_id']==u['id'] and r['status']=='approved']
            out.append({**u,'employee_status':self.employee_status(actor,u['id']),'done':len(rr),'score':sum(r['score'] for r in rr)/len(rr) if rr else None,
                'hours':sum(r['hours'] for r in rr),'active_count':sum(t['worker_id']==u['id'] and t['status'] not in ('approved','cancelled') for t in tasks)})
        return sorted(out,key=lambda u:u['score'] if u['score'] is not None else -1,reverse=True)
    def submit(self,actor,tid,*,photo_sources,**kwargs):
        photos=[]
        for source in photo_sources:
            p=Path(source)
            if not p.is_file() or p.stat().st_size>8*1024*1024:raise ValueError('Фото должно быть не больше 8 МБ.')
            photos.append({'name':p.name,'content':base64.b64encode(p.read_bytes()).decode()})
        return self.call('submit',tid,photos=photos,**kwargs)
    def ensure_photos(self,report):
        for name in report['photos']:
            if Path(name).name!=name:raise ValueError('Некорректное имя фото.')
            p=self.photos/name
            if not p.exists():p.write_bytes(self.request('/api/photos/'+quote(name,safe=''),binary=True))
    def export_reports(self,actor,path):
        self.refresh_snapshot()
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f,delimiter=';');writer.writerow(['Отчёт','Наряд','Работа','Сотрудник','Статус','Часы','Оценка мастера','Материалы, тг','Комментарий','Дата'])
            for r in self.reports(actor):
                values=[r['id'],r['task_id'],r['title'],r['worker_name'],STATUS[r['status']],r['hours'],r['score'],round(sum(m['quantity']*m['price'] for m in r['materials']),2),r['comment'],r['created']]
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in values])

def _proxy(method):
    def invoke(self,actor,*args,**kwargs):return self.call(method,*args,**kwargs)
    return invoke

for _method in ('create_task','claim','reschedule','transition','review','add_user','set_active','reset_password','support_update_task','set_shift',
                'reassign_task','save_reference','delete_reference','acknowledge_alert','set_notification_settings'):
    setattr(RemoteStore,_method,_proxy(_method))
