"""Regression tests for the audit findings. Default: isolated SQLite.

TEST_DATABASE_URL may target a dedicated localhost PostgreSQL test database.
Never point it at the team's live database. This suite writes synthetic test rows.
"""
import base64,json,os,sqlite3,tempfile,time,unittest,uuid
from contextlib import closing
from datetime import date,datetime,timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from PIL import Image
from server.api import create_app
from server.config import Settings
from app.case_store import SQLiteConnection,moment,stamp

DATABASE=os.environ.get('TEST_DATABASE_URL','')
if DATABASE:
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(DATABASE).get('host') not in ('127.0.0.1','localhost'):raise RuntimeError('Only a dedicated localhost TEST_DATABASE_URL is allowed.')

class MemoryStorage:
    def __init__(self,*args):self.files={}
    def ensure_bucket(self):pass
    def upload(self,name,data):self.files[name]=data
    def download(self,name):
        if name not in self.files:raise FileNotFoundError(name)
        return self.files[name]
    def delete(self,name):self.files.pop(name,None)

def image_data(color='blue',exif_time=None):
    stream=BytesIO();image=Image.new('RGB',(80,50),color);exif=Image.Exif()
    if exif_time:exif[36867]=exif_time
    image.save(stream,'JPEG',exif=exif)
    return {'name':'test.jpg','content':base64.b64encode(stream.getvalue()).decode()}

class Case1Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.storage=MemoryStorage()
        self.settings=Settings(seed_demo=True,data_dir=self.folder,database_url=DATABASE,database_pool_size=1,ai_enabled=False,bootstrap_password='DemoOnly-2026!')
        with patch('server.storage.SupabaseStorage',return_value=self.storage):self.app=create_app(self.settings)
        self.client=TestClient(self.app);self.store=self.app.state.store
        pw='DemoOnly-2026!' if DATABASE else '1234'
        self.master,self.m=self.login('master',pw,'master');self.admin,self.a=self.login('admin',pw,'admin')
        username='test_'+uuid.uuid4().hex[:16]
        self.rpc('add_user',self.admin,args=[username,'Демо тест','Электрик','worker','test-password'])
        self.worker,self.w=self.login(username,'test-password','worker')
        self.catalog=self.client.get('/api/catalogs',headers=self.master).json();self.equipment=self.catalog['equipment'][0]
        self.site=next(x for x in self.catalog['sites'] if x['id']==self.equipment['site_id'])
        self.day=(date.today()+timedelta(days=180)).isoformat();self.created=[]
    def tearDown(self):
        self.client.close();self.store.close();self.temp.cleanup()
    def login(self,user,password,role):
        response=self.client.post('/api/login',json={'username':user,'password':password,'role':role});self.assertEqual(response.status_code,200,response.text)
        body=response.json();return {'Authorization':'Bearer '+body['token']},body['user']
    def rpc(self,method,headers,args=None,kwargs=None,photos=None,request_id=None,expected=200):
        response=self.client.post('/api/call/'+method,headers=headers,json={'args':args or [],'kwargs':kwargs or {},'photos':photos or [],'request_id':request_id or uuid.uuid4().hex})
        self.assertEqual(response.status_code,expected,response.text)
        return response.json().get('result') if expected==200 else response
    def task_fields(self,**changes):
        return {'title':'Тестовый ремонт агрегата','description':'Проверить привод и выполнить контрольный запуск.','site':self.site['name'],'equipment':self.equipment['name'],'site_id':self.site['id'],'equipment_id':self.equipment['id'],'priority':'high','kind':'Внеплановая','duration':1,'day':self.day,'start':8,'deadline':self.day+'T18:00','worker_id':self.w['id'],**changes}
    def create(self,**changes):
        tid=self.rpc('create_task',self.master,kwargs=self.task_fields(**changes));self.created.append(tid);return tid
    def start(self,tid):
        self.rpc('transition',self.worker,args=[tid,'accepted']);self.rpc('transition',self.worker,args=[tid,'inProgress'])
    def submit(self,tid,photos=None,materials=None):
        return self.rpc('submit',self.worker,args=[tid],kwargs={'work':'Заменён подшипник, проверены крепления.','result':'Контрольный запуск выполнен.','defect':self.catalog['defect_codes'][1]['code'],'hours':1,'materials':materials or []},photos=photos or [])
    def test_workflow_materials_photo_revision_and_facts(self):
        tid=self.create();self.rpc('transition',self.worker,args=[tid,'queued']);self.rpc('transition',self.worker,args=[tid,'inProgress'])
        self.rpc('transition',self.worker,args=[tid,'paused','Ожидание материалов']);self.rpc('transition',self.worker,args=[tid,'inProgress'])
        rid=self.submit(tid)
        self.rpc('review',self.master,args=[rid,True,90,'Работа принята'],expected=400)
        self.rpc('review',self.master,args=[rid,False,None,'Добавьте фото результата'])
        mat=next((m for m in self.catalog['materials'] if m['unit']=='кг'),None)
        if mat is None:mat=self.catalog['materials'][0]
        quantity=1000 if mat['unit']=='кг' else 1;unit='г' if mat['unit']=='кг' else mat['unit']
        rid2=self.submit(tid,photos=[image_data()],materials=[{'material_id':mat['id'],'name':'Подмена имени','quantity':quantity,'unit':unit,'price':.01}])
        self.rpc('review',self.master,args=[rid2,True,92,'Фото и контрольная проверка представлены'])
        task=self.rpc('task',self.master,args=[tid]);self.assertEqual(task['status'],'approved')
        for field in ('issued_at','accepted_at','started_at','completed_at','closed_at'):self.assertTrue(task[field],field)
        reports=self.store.reports(self.m,task_ids=[tid]);current=reports[0]
        self.assertEqual(current['materials'][0]['quantity'],1);self.assertEqual(current['materials'][0]['price'],float(mat['unit_price']))
        self.assertEqual(reports[1]['status'],'superseded')
        events=self.rpc('events',self.master,args=[tid]);self.assertTrue(all(e['action']!='comment' for e in events));self.assertTrue(any(e['from_status']=='inProgress' and e['to_status']=='paused' and e['reason'] for e in events))
        photos=self.rpc('photos_for_task',self.master,args=[tid]);self.assertTrue(photos[0]['sha256']);self.assertGreater(photos[0]['byte_size'],0)
        self.assertEqual(self.client.get('/api/photos/'+photos[0]['object_key'],headers=self.worker).status_code,200)
    def test_atomic_rpc_and_content_bound_id(self):
        fields=self.task_fields();request_id=uuid.uuid4().hex
        from server.postgres import Connection
        cls=Connection if DATABASE else SQLiteConnection;execute=cls.execute;state={'failed':False}
        def faulty(c,sql,args=()):
            if sql.startswith('INSERT INTO rpc_results') and not state['failed']:state['failed']=True;raise sqlite3.OperationalError('Injected receipt write failure')
            return execute(c,sql,args)
        before=len(self.store.tasks(self.m));before_files=set(self.storage.files) if DATABASE else set(self.store.photos.iterdir())
        with patch.object(cls,'execute',faulty):self.rpc('create_task',self.master,kwargs=fields,photos=[image_data()],request_id=request_id,expected=503)
        self.assertEqual(len(self.store.tasks(self.m)),before)
        self.assertEqual(set(self.storage.files) if DATABASE else set(self.store.photos.iterdir()),before_files)
        tid=self.rpc('create_task',self.master,kwargs=fields,photos=[image_data()],request_id=request_id)
        self.assertEqual(self.rpc('create_task',self.master,kwargs=fields,photos=[image_data()],request_id=request_id),tid)
        self.assertEqual(len(self.store.tasks(self.m)),before+1)
        self.rpc('create_task',self.master,kwargs={**fields,'title':'Другое содержимое запроса'},photos=[image_data()],request_id=request_id,expected=409)
    def test_catalog_rejections_and_four_priorities(self):
        self.rpc('create_task',self.master,kwargs=self.task_fields(equipment='Насос с опечаткой',equipment_id=None),expected=400)
        for i,priority in enumerate(('urgent','high','normal','scheduled')):self.create(priority=priority,start=8+i)
        tid=self.created[0];self.start(tid)
        mat=self.catalog['materials'][0]
        self.rpc('submit',self.worker,args=[tid],kwargs={'work':'Проверен привод оборудования','result':'Контроль выполнен','defect':self.catalog['defect_codes'][0]['code'],'hours':1,'materials':[{'material_id':mat['id'],'quantity':1,'unit':'несовместимая','price':1}]},expected=400)
    def test_reassignment_preserves_old_report_and_membership(self):
        tid=self.create();self.start(tid);rid=self.submit(tid);self.rpc('review',self.master,args=[rid,False,None,'Требуется повторная проверка'])
        username='test_'+uuid.uuid4().hex[:16];self.rpc('add_user',self.admin,args=[username,'Демо другой работник','Механик','worker','test-password']);other,person=self.login(username,'test-password','worker')
        self.rpc('reassign_task',self.master,args=[tid,person['id'],self.day,9,'Смена ответственного исполнителя'])
        rows=self.store.reports(self.m,task_ids=[tid]);self.assertEqual(rows[0]['worker_id'],self.w['id']);self.assertEqual(rows[0]['status'],'superseded')
        with self.store.transaction() as c:assignments=c.execute('SELECT * FROM task_assignments WHERE task_id=? ORDER BY id',(tid,)).fetchall()
        self.assertEqual(len(assignments),2);self.assertTrue(assignments[0]['ended_at']);self.assertIsNone(assignments[1]['ended_at'])
    def test_overnight_shift_and_cross_day_overlap(self):
        self.rpc('set_shift',self.master,args=[self.w['id'],self.day,22,6])
        tid=self.create(start=2,deadline=(date.fromisoformat(self.day)+timedelta(days=1)).isoformat()+'T06:00')
        self.assertEqual(self.rpc('task',self.master,args=[tid])['start'],26)
        otherday=(date.fromisoformat(self.day)+timedelta(days=1)).isoformat();self.rpc('set_shift',self.master,args=[self.w['id'],otherday,0,8])
        self.rpc('create_task',self.master,kwargs=self.task_fields(day=otherday,start=2,deadline=otherday+'T08:00'),expected=400)
        clock=datetime.combine(date.fromisoformat(otherday),datetime.min.time())+timedelta(hours=3)
        self.assertNotEqual(self.store.employee_status(self.m,self.w['id'],clock),'off')
    def test_notifications_thresholds_dedup_and_permissions(self):
        tid=self.create(priority='urgent')
        t=self.store.task(self.m,tid);at=moment(t['issued_at'])+timedelta(minutes=3,seconds=1)
        self.store.notification_tick(at);self.store.notification_tick(at)
        with self.store.transaction() as c:rows=c.execute("SELECT * FROM notification_outbox WHERE task_id=? AND kind='unaccepted' AND user_id=?",(tid,self.m['id'])).fetchall()
        self.assertEqual(len(rows),1)
        self.rpc('acknowledge_notification',self.worker,args=[rows[0]['id']],expected=403)
        self.rpc('acknowledge_notification',self.master,args=[rows[0]['id']])
        self.start(tid);self.store.notification_tick(at+timedelta(minutes=10))
        due=moment(t['deadline']);self.store.notification_tick(due-timedelta(minutes=20));self.store.notification_tick(due+timedelta(minutes=1));self.store.notification_tick(due+timedelta(minutes=31))
        with self.store.transaction() as c:
            kinds=[r['kind'] for r in c.execute('SELECT kind FROM notification_outbox WHERE task_id=? AND user_id=?',(tid,self.w['id']))]
        self.assertEqual(kinds.count('deadline_reminder'),1);self.assertEqual(kinds.count('overdue'),2)
    def test_downtime_union_and_period_rating(self):
        tid=self.create();self.start(tid)
        begin=datetime.now().replace(microsecond=0)-timedelta(hours=5)
        first=self.rpc('start_downtime',self.master,args=[tid,'Отказ привода',begin.isoformat()]);self.rpc('end_downtime',self.master,args=[first,(begin+timedelta(hours=3)).isoformat()])
        second=self.rpc('start_downtime',self.master,args=[tid,'Ожидание запчастей',(begin+timedelta(hours=2)).isoformat()]);self.rpc('end_downtime',self.master,args=[second,(begin+timedelta(hours=4)).isoformat()])
        rid=self.submit(tid,photos=[image_data()]);self.rpc('review',self.master,args=[rid,True,90,'Ремонт принят'])
        result=self.store.analytics(self.m,(begin-timedelta(hours=1)).isoformat(),(datetime.now()+timedelta(hours=1)).isoformat(),worker_id=self.w['id'])
        row=next(r for r in result['equipment_downtime'] if r['equipment_id']==self.equipment['id']);self.assertEqual(row['hours'],4)
        rank=result['workers'][0];self.assertEqual(rank['done'],1);self.assertEqual(rank['score'],96);self.assertEqual(sum(result['weights'].values()),1)
        self.rpc('analytics',self.worker,args=[begin.isoformat(),(datetime.now()+timedelta(hours=1)).isoformat()],kwargs={'worker_id':self.m['id']},expected=403)
    def test_snapshot_budget_and_pagination(self):
        from server.postgres import Connection
        cls=Connection if DATABASE else SQLiteConnection;execute=cls.execute;counter={'sql':0}
        def counted(c,sql,args=()):counter['sql']+=1;return execute(c,sql,args)
        with patch.object(cls,'execute',counted):response=self.client.get('/api/snapshot',headers=self.master)
        self.assertEqual(response.status_code,200,response.text);self.assertLess(counter['sql'],60)
        snap=response.json();self.assertIn('history_days',snap);self.assertIn('metrics',snap);self.assertLess(len(response.content),600000)
        page=self.client.get('/api/tasks?limit=2',headers=self.master);self.assertEqual(page.status_code,200);self.assertLessEqual(len(page.json()['items']),2)
        print('Snapshot measurement:',{'backend':'PostgreSQL' if DATABASE else 'SQLite','sql':counter['sql'],'bytes':len(response.content),'tasks':len(snap['tasks']),'reports':len(snap['reports'])})
    def test_truncated_snapshot_keeps_actual_availability(self):
        tid=self.create();self.start(tid);self.create(start=9)
        today=date.today().isoformat();self.rpc('set_shift',self.master,args=[self.w['id'],today,0,24])
        # A newer issued task hides the running one in the visible page; status must still be busy.
        response=self.client.get('/api/snapshot?limit=1',headers=self.master);self.assertEqual(response.status_code,200,response.text)
        snap=response.json();self.assertTrue(snap['truncated']);self.assertEqual(snap['employee_status'][str(self.w['id'])],'busy')
    def test_future_and_duplicate_photos(self):
        tid=self.create();self.start(tid)
        kwargs={'work':'Проверено состояние оборудования','result':'Контроль выполнен','defect':self.catalog['defect_codes'][0]['code'],'hours':1,'materials':[]}
        self.rpc('submit',self.worker,args=[tid],kwargs=kwargs,photos=[image_data(exif_time='2099:01:01 10:00:00')],expected=400)
        self.rpc('submit',self.worker,args=[tid],kwargs=kwargs,photos=[image_data(),image_data()],expected=400)
    def test_manager_role_is_removed(self):
        username='test_'+uuid.uuid4().hex[:16]
        self.rpc('add_user',self.admin,args=[username,'Удалённая роль','Участок','manager','test-password'],expected=400)
        self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':'1234','role':'manager'}).status_code,400)
        self.assertNotIn('manager',{u['role'] for u in self.store.users(self.a)})
    def test_ai_norms_privacy_and_human_closure(self):
        norm=self.rpc('catalog_upsert',self.master,args=['work_norms',{'equipment_type':self.equipment['equipment_type'],'kind':'Внеплановая','defect_code_id':None,'hours':2,'complexity':2,'active':1}])
        material=self.catalog['materials'][0];self.rpc('set_material_norm',self.master,args=[norm,material['id'],.5])
        tid=self.rpc('create_task',self.master,kwargs=self.task_fields(norm_id=norm,description=self.w['name']+' проверяет привод. Контакт private@example.com'),photos=[image_data('red')])
        self.start(tid);self.settings.ai_enabled=True;rid=self.submit(tid)
        with self.store.transaction() as c:
            task=dict(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone());report=dict(c.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone())
            task,report=self.store.ai_context(c,task,report)
        self.assertEqual(task['norms']['time']['hours'],2);self.assertEqual(task['norms']['materials'][0]['quantity'],.5);self.assertEqual(len(report['before_photos']),1)
        self.assertNotIn(self.w['name'],task['description']);self.assertNotIn('private@example.com',task['description'])
        self.store.finish_ai(rid,{'score':95,'verdict':'accepted','summary':'Тестовый ответ модели','findings':[],'criteria':{},'confidence':.8,'quality_1_5':5})
        report=self.store.reports(self.m,task_ids=[tid])[0];self.assertEqual(report['ai']['verdict'],'needs_clarification');self.assertEqual(report['ai']['quality_1_5'],5)
        self.assertEqual(self.store.task(self.m,tid)['status'],'submitted');self.rpc('review',self.master,args=[rid,True,95,'Проверка мастера'],expected=400)
        events=self.store.events(self.m,tid);self.assertTrue(any(e['action']=='ai_completed' and e['actor_kind']=='system' for e in events))
        self.assertEqual(self.client.get('/api/chat',headers=self.worker).status_code,403)
        self.assertEqual(self.client.get('/api/chat',headers=self.master).status_code,200)
        context=self.store.assistant_context(self.m);self.assertTrue(all('name' not in p and 'username' not in p for p in context['workers_now']))
    def test_refusal_assessment_keeps_original_worker(self):
        tid=self.create();self.rpc('transition',self.worker,args=[tid,'rejected','Нет допуска к оборудованию'])
        self.rpc('assess_refusal',self.master,args=[tid,True,'Отказ обоснован отсутствием допуска'])
        self.rpc('reassign_task',self.master,args=[tid,self.w['id'],self.day,9,'Повторная выдача после инструктажа'])
        with self.store.transaction() as c:row=c.execute('SELECT * FROM task_refusals WHERE task_id=?',(tid,)).fetchone()
        self.assertEqual(row['worker_id'],self.w['id']);self.assertEqual(row['justified'],1)
    def test_brigade_snapshot_survives_employee_transfer(self):
        first,second=self.catalog['brigades'][:2]
        self.rpc('set_employee_profile',self.admin,args=[self.w['id'],'Электрик',4,first['id']])
        tid=self.create();self.start(tid)
        self.rpc('set_employee_profile',self.admin,args=[self.w['id'],'Электрик',4,second['id']])
        rid=self.submit(tid,photos=[image_data()]);self.rpc('review',self.master,args=[rid,True,90,'Работа проверена'])
        report=self.store.reports(self.m,task_ids=[tid])[0];self.assertEqual(report['brigade_id'],first['id'])
    def test_notification_retry_adapter(self):
        from server.notifications import NotificationDispatcher
        tid=self.create();self.settings.notification_webhook='https://push.example.invalid/events';self.settings.notification_webhook_key='test-notification-key-1234567890123456789'
        dispatcher=NotificationDispatcher(self.store,self.settings)
        with self.store.transaction(write=True) as c:c.execute("UPDATE notification_outbox SET next_attempt_at='2099-01-01T00:00:00' WHERE task_id<>?",(tid,))
        with patch('server.notifications.urlopen',side_effect=OSError('Injected outage')):dispatcher.tick()
        with self.store.transaction(write=True) as c:
            row=c.execute('SELECT * FROM notification_outbox WHERE task_id=? AND user_id=? ORDER BY id LIMIT 1',(tid,self.w['id'])).fetchone();self.assertEqual(row['status'],'failed');self.assertEqual(row['attempts'],1)
            c.execute('UPDATE notification_outbox SET next_attempt_at=? WHERE id=?',((moment(stamp())-timedelta(seconds=1)).isoformat(),row['id']))
        with patch('server.notifications.urlopen') as sender:
            sender.return_value.__enter__.return_value.status=200;dispatcher.tick();self.assertTrue(sender.called)
        with self.store.transaction() as c:after=c.execute('SELECT status,attempts FROM notification_outbox WHERE id=?',(row['id'],)).fetchone()
        self.assertEqual(after['status'],'sent');self.assertEqual(after['attempts'],2)
    @unittest.skipUnless(DATABASE and not os.environ.get('TEST_PGLITE_SOCKETS'),'Native PostgreSQL constraint test; PGlite socket error recovery is tested via in-process SQL instead')
    def test_sql_constraints_and_search_path(self):
        tid=self.create()
        for sql,args in [("UPDATE tasks SET status='approved' WHERE id=?",(tid,)),('UPDATE tasks SET master_id=? WHERE id=?',(self.w['id'],tid)),("UPDATE tasks SET equipment='Опечатка' WHERE id=?",(tid,))]:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store.transaction(write=True) as c:c.execute(sql,args)
        with self.store.transaction(write=True) as c:
            c.connection.execute("SELECT set_config('naryadai.service_write','',true)")
            c.execute('SET LOCAL search_path TO public');c.execute("UPDATE naryadai.tasks SET priority='scheduled' WHERE id=?",(tid,))
        self.assertTrue(any(e['action']=='db_change' for e in self.store.events(self.m,tid)))

class LegacyMigrationTests(unittest.TestCase):
    def test_sqlite_migration_backup_restore_and_repeat(self):
        from app.store import LegacyStore,Store,password_hash
        import ast,inspect,textwrap
        ddl=next(node.value for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(LegacyStore.__init__)))) if isinstance(node,ast.Constant) and isinstance(node.value,str) and 'CREATE TABLE IF NOT EXISTS users' in node.value)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'naryadai.db'
            with closing(sqlite3.connect(path)) as c:
                c.executescript(ddl)
                for uid,name,role in [(1,'master','master'),(2,'worker1','worker')]:c.execute('INSERT INTO users(id,username,name,job,role,salt,password_hash) VALUES(?,?,?,?,?,?,?)',(uid,name,'Исторический '+name,'Электрик',role,'00'*16,password_hash('old-password','00'*16)))
                c.execute("INSERT INTO tasks(id,title,description,site,equipment,priority,kind,duration,day,start,deadline,worker_id,master_id,status,created) VALUES(1,'Исторический ремонт','Описание исторической работы','Старый участок','Насос','urgent','Внеплановая',1,'2026-01-01',8,'2026-01-01T18:00',2,1,'approved','2026-01-01T08:00')")
                c.execute("INSERT INTO reports(id,task_id,worker_id,work,result,defect,hours,materials,photos,status,score,comment,reviewer_id,created,reviewed) VALUES(1,1,2,'Историческая работа','Контроль выполнен','D-01 · Износ',1,?,'[]','approved',90,'Старое решение',1,'2026-01-01T10:00','2026-01-01T11:00')",(json.dumps([{'name':'Смазка','quantity':1000,'unit':'г','price':1}]),))
                c.execute('CREATE TABLE materials(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT UNIQUE,unit TEXT,unit_price REAL)');c.execute("INSERT INTO materials VALUES(1,'M1','Смазка','кг',1000)");c.commit()
            s=Store(directory);master=s.authenticate('master','old-password','master');self.assertEqual(len(s.tasks(master)),1)
            report=s.reports(master)[0];self.assertEqual(report['materials'][0]['quantity'],1);self.assertEqual(report['materials'][0]['price'],1000);self.assertEqual(report['data_origin'],'legacy_report_time')
            backup=Path(directory)/'naryadai-before-v2.db';self.assertTrue(backup.is_file())
            with closing(sqlite3.connect(backup)) as old:self.assertEqual(old.execute('SELECT title FROM tasks').fetchone()[0],'Исторический ремонт');self.assertEqual(json.loads(old.execute('SELECT materials FROM reports').fetchone()[0])[0]['quantity'],1000)
            # Reopen preserves row IDs and the assignment history; no duplicate migration.
            again=Store(directory)
            with again.transaction() as c:self.assertEqual(c.execute('SELECT count(*) FROM task_assignments').fetchone()[0],1)
            restored=Path(directory)/'restored';restored.mkdir()
            import shutil
            shutil.copy2(backup,restored/'naryadai.db');restored_store=Store(restored);self.assertEqual(restored_store.task(restored_store.authenticate('master','old-password','master'),1)['title'],'Исторический ремонт')

if __name__=='__main__':unittest.main(verbosity=2)
