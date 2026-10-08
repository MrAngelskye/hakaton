"""Bounded, read-only retrieval. Source facts stay separate from model hypotheses."""
import json,re
from datetime import date,timedelta
from app.case_store import TZ
from datetime import datetime
STOP={'какие','какой','котор','покаж','сколь','наряд','задач','сегод','работ','отчёт','отчет','сдела','можно','такое','почему','пожал','нужно','данны','месяц','недел','после','перед'}
def words(text):return {w[:5] for w in re.findall(r'[\w-]{3,}',text.lower()) if w[:5] not in STOP and not w.isdigit()}
def period(message):
    today=datetime.now(TZ).date();end=today+timedelta(days=1);start=today-timedelta(days=89);explicit=False
    dates=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',message)
    if dates:
        start=date.fromisoformat(dates[0]);end=date.fromisoformat(dates[1])+timedelta(days=1) if len(dates)>1 else start+timedelta(days=1);explicit=True
    elif 'сегодня' in message.lower():start=today;explicit=True
    elif 'вчера' in message.lower():start=today-timedelta(days=1);end=today;explicit=True
    elif 'недел' in message.lower():start=today-timedelta(days=6);explicit=True
    elif 'месяц' in message.lower():start=today-timedelta(days=29);explicit=True
    days=re.search(r'за\s+(\d{1,3})\s+дн',message.lower())
    if days:start=today-timedelta(days=min(365,max(1,int(days[1])))-1);explicit=True
    if start>=end or (end-start).days>366:raise ValueError('Период должен быть от 1 до 366 дней.')
    return start.isoformat(),end.isoformat(),explicit
class Knowledge:
    def __init__(self,store,control):self.store=store;self.control=control
    def reference_facts(self,c,tokens,redact):
        if not tokens:return []
        references=[]
        queries={
            'material':"SELECT m.code,m.name,m.unit,m.unit_price,p.price_known,p.company_usage_confirmed,p.note,p.source_id FROM materials m JOIN material_reference_metadata p ON p.material_id=m.id",
            'template':"SELECT template_id,title,equipment_category,problem_description,closeout_requirements,source_id,status FROM work_order_templates",
            'equipment_type':"SELECT code,name,note,source_id,company_context FROM equipment_reference_types",
            'site':"SELECT s.code,s.name,p.note,p.source_id,p.company_confirmed FROM sites s JOIN reference_provenance p ON p.entity_type='sites' AND p.entity_key=s.code",
        }
        for kind,query in queries.items():
            for row in c.execute(query):
                record=dict(row);score=len(tokens&words(json.dumps(record,ensure_ascii=False)))
                if not score:continue
                if kind=='material' and not record['price_known']:record['unit_price']=None
                source=c.execute('SELECT title,url,evidence FROM reference_sources WHERE source_id=?',(record['source_id'],)).fetchone()
                record.update(kind=kind,source=dict(source) if source else None)
                for key,value in record.items():
                    if isinstance(value,str):record[key]=value[:700]
                references.append((score,json.loads(redact(json.dumps(record,ensure_ascii=False)))))
        references.sort(key=lambda item:item[0],reverse=True)
        return [record for _,record in references[:5]]
    def retrieve(self,user,message):
        start,end,explicit=period(message);tokens=words(message);ids={int(n) for n in re.findall(r'(?:нр[-\s]*|наряд\s*[№#]?\s*)(\d+)',message,re.I)}
        with self.store.transaction() as c:
            self.store.require(c,user,('master','admin'))
            names=[dict(r) for r in c.execute('SELECT id,name,username FROM users')]
            def redact(text):
                for p in sorted(names,key=lambda x:len(x['name']),reverse=True):
                    text=text.replace(p['name'],f'Сотрудник #{p["id"]}')
                    text=re.sub(r'(?<!\w)'+re.escape(p['username'])+r'(?!\w)',f'Сотрудник #{p["id"]}',text,flags=re.I)
                text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[email]',text)
                return re.sub(r'(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)','[номер]',text)
            tasks=self.store.tasks(user,limit=2000);reports=self.store.reports(user,task_ids=[t['id'] for t in tasks])
            wanted_workers={p['id'] for p in names if p['name'].lower() in message.lower() or re.search(r'(?<!\w)'+re.escape(p['username'])+r'(?!\w)',message,re.I)}
            ranks=[]
            for task in tasks:
                if explicit and not start<=task['day']<end and task['id'] not in ids:continue
                if wanted_workers and task.get('worker_id') not in wanted_workers:continue
                score=100 if task['id'] in ids else len(tokens&words(task['title']+' '+task['description']+' '+task['equipment']))
                if re.search(r'текущ|сейчас|очеред|приостан',message,re.I) and task['status'] not in ('approved','cancelled'):score+=2
                if score or wanted_workers:ranks.append((score,task))
            ranks.sort(key=lambda x:(x[0],x[1]['id']),reverse=True)
            selected=[t for _,t in ranks[:5]];records=[]
            for task in selected:
                entry={k:task.get(k) for k in ('id','title','description','equipment','site','status','priority','day','deadline','duration','worker_id','data_origin')}
                entry={k:(v[:700] if isinstance(v,str) else v) for k,v in entry.items()}
                entry['reports']=[{k:r.get(k) for k in ('id','status','work','result','hours','materials','score','comment','defect','data_origin')} for r in reports if r['task_id']==task['id']][:1]
                for r in entry['reports']:
                    for k,v in r.items():
                        if isinstance(v,str):r[k]=v[:700]
                records.append(json.loads(redact(json.dumps(entry,ensure_ascii=False))))
            documents=[]
            for doc in c.execute('SELECT id,title,body FROM knowledge_documents'):
                chunks=re.split(r'\n\s*\n',doc['body'])
                for index,chunk in enumerate(chunks):
                    score=len(tokens&words(doc['title']+' '+chunk))
                    if score:documents.append((score,{'id':doc['id'],'title':doc['title'],'fragment':index+1,'text':redact(chunk[:1000])}))
            documents.sort(key=lambda x:x[0],reverse=True)
            references=self.reference_facts(c,tokens,redact)
            analytics=self.store.analytics(user,start,end)
            counts={t:c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('users','tasks','reports','materials','work_order_templates','training_photos')}
            statuses=self.store.availability(user,datetime.now(TZ).date().isoformat())[2]
            facts={'period':{'start':start,'end_exclusive':end,'default_period':not explicit},'database_counts':counts,'calculated':{'counts':analytics['counts'],'failures':analytics['failures'][:8],'materials':analytics['materials'][:12],'workers':[{'id':w['id'],'done':w['done'],'score':w.get('score'),'on_time':w.get('components',{}).get('on_time')} for w in analytics['workers']][:25]},'records':records,'references':references,'documents':[d for _,d in documents[:3]],'workers_now':[{'worker_id':int(k),'status':v} for k,v in statuses.items()],'database_found':bool(records or references),'documents_found':bool(documents),'requested_task_ids':sorted(ids),'missing_task_ids':sorted(ids-{t['id'] for t in selected}),'web_allowed':self.control.flag(c,'web_enabled',True),'public_query':redact(message)[:500],'note':'Факты только из базы. Синтетические записи — учебные. references — открытые справочники, а не история предприятия; неизвестные цены — null, шаблоны draft требуют проверки мастером. Не выдавай предположения за факт; укажи период и источник.'}

            from server.training import requested, retrieve
            if requested(message):
                if getattr(getattr(self.store,'settings',None),'database_url',''):
                    facts['training']=retrieve(c,message,tokens)
                else:
                    facts['training']={'available':False,'synthetic':True,'note':'Учебная база доступна на общем облачном сервере.'}
            return facts
