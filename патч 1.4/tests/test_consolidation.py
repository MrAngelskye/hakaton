"""Integration regressions for the consolidated desktop/web clients and DB 002."""
import os,sys,tempfile,unittest,uuid,json,sqlite3
from datetime import date,timedelta
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from server.api import create_app
from server.config import Settings
from app.store import Store
from tools.import_demo import import_demo

class ConsolidatedAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.app=create_app(Settings(seed_demo=True,data_dir=Path(cls.temp.name),ai_enabled=False));cls.client=TestClient(cls.app)
        cls.headers={}
        for role,login in [('master','master'),('worker','worker1'),('worker2','worker2'),('admin','admin'),('manager','manager')]:
            r=cls.client.post('/api/login',json={'username':login,'password':'1234','role':'worker' if role=='worker2' else role});assert r.status_code==200,r.text
            cls.headers[role]={'Authorization':'Bearer '+r.json()['token']}
        cls.store=cls.app.state.store
        cls.master=cls.store.authenticate('master','1234','master');cls.worker=cls.store.authenticate('worker1','1234','worker')
        cls.admin=cls.store.authenticate('admin','1234','admin');cls.worker2=cls.store.authenticate('worker2','1234','worker')
    @classmethod
    def tearDownClass(cls):cls.client.close();cls.store.close();cls.temp.cleanup()
    def call(self,role,method,args=(),kwargs=None,request_id=None):
        return self.client.post('/api/call/'+method,headers=self.headers[role],json={'args':list(args),'kwargs':kwargs or {},'request_id':request_id or uuid.uuid4().hex,'photos':[]})
    def test_public_shell_and_protected_data(self):
        for url in ('/','/web/app.js','/web/styles.css','/sw.js','/web/manifest.webmanifest','/assets/branding/km-logo-white.svg'):
            self.assertEqual(self.client.get(url).status_code,200,url)
        self.assertEqual(self.client.get('/api/catalogs').status_code,401)
        self.assertEqual(self.client.get('/api/snapshot').status_code,401)
        self.assertEqual(self.client.get('/health').json()['version'],'1.7')
    def test_web_payload_and_complete_cycle(self):
        cat=self.client.get('/api/catalogs',headers=self.headers['master']).json();e=cat['equipment'][0];s=next(s for s in cat['sites'] if s['id']==e['site_id'])
        day=(date.today()+timedelta(days=20)).isoformat()
        payload=dict(title='Проверить конвейер',description='Осмотр привода и контрольный запуск',site=s['name'],equipment=e['name'],site_id=s['id'],equipment_id=e['id'],priority='scheduled',kind='Плановая',duration=1,day=day,start=8,deadline=day+'T18:00',worker_id=self.worker['id'],brigade_id=None,norm_id=None)
        req=uuid.uuid4().hex;r=self.call('master','create_task',kwargs=payload,request_id=req);self.assertEqual(r.status_code,200,r.text);tid=r.json()['result']
        self.assertEqual(self.call('master','create_task',kwargs=payload,request_id=req).json()['result'],tid)
        self.assertEqual(self.call('worker','transition',[tid,'accepted']).status_code,200)
        self.assertEqual(self.call('worker','transition',[tid,'inProgress']).status_code,200)
        report=self.call('worker','submit',[tid],dict(work='Проверены соединения, выполнен контрольный запуск',result='Работа оборудования стабильна',defect=cat['defect_codes'][0]['code'],hours=1,materials=[]))
        self.assertEqual(report.status_code,200,report.text);rid=report.json()['result']
        self.assertEqual(self.call('master','review',[rid,True,85,'Результат проверен мастером']).status_code,200)
        hist=self.call('master','equipment_history',[e['id']]);self.assertEqual(hist.status_code,200,hist.text);self.assertIn(tid,[t['id'] for t in hist.json()['result']['tasks']])
        self.assertEqual(self.call('worker','equipment_history',[e['id']]).status_code,403)
        denied=self.call('manager','create_task',kwargs=payload);self.assertEqual(denied.status_code,403)
    def test_catalog_editor_contract(self):
        values={'code':'CONSOLIDATED','name':'Учебный участок объединения'}
        r=self.call('admin','catalog_upsert',['sites',values,None]);self.assertEqual(r.status_code,200,r.text)
        rid=r.json()['result'];values['name']='Участок после изменения'
        self.assertEqual(self.call('master','catalog_upsert',['sites',values,rid]).status_code,200)
        self.assertEqual(self.call('worker','catalog_upsert',['sites',values,rid]).status_code,403)
    def test_brigade_snapshot_carries_assignment_members(self):
        cat=self.store.catalogs(self.admin);bid=cat['brigades'][0]['id']
        self.store.set_employee_profile(self.admin,self.worker['id'],'Механик',4,bid)
        self.store.set_employee_profile(self.admin,self.worker2['id'],'Механик',4,bid)
        e=cat['equipment'][1];s=next(s for s in cat['sites'] if s['id']==e['site_id']);day=(date.today()+timedelta(days=21)).isoformat()
        tid=self.store.create_task(self.master,title='Бригадный осмотр конвейера',description='Проверить агрегат всей назначенной бригадой',site=s['name'],equipment=e['name'],equipment_id=e['id'],priority='normal',kind='Плановая',duration=1,day=day,start=8,deadline=day+'T18:00',worker_id=self.worker['id'],brigade_id=bid)
        snap=self.client.get('/api/snapshot?day='+day,headers=self.headers['worker2']).json();task=next(t for t in snap['tasks'] if t['id']==tid)
        self.assertIn(self.worker2['id'],task['member_ids'])
        self.assertNotEqual(task['worker_id'],self.worker2['id'])
        self.assertEqual(self.call('worker2','transition',[tid,'accepted']).status_code,200)

class DemoDatabase(unittest.TestCase):
    def test_import_migration_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'demo';info=import_demo(target);self.assertEqual(info['counts']['tasks'],608)
            self.assertEqual(len(list((target/'photos').glob('*.jpg'))),705)
            store=Store(target);admin=store.authenticate('admin','DemoOnly-2026!','admin')
            self.assertEqual(len(store.catalogs(admin)['equipment']),25)
            summary=store.analytics(admin,'2026-07-01','2026-10-10')
            self.assertEqual(len(summary['brigades']),3)
            self.assertTrue(all(b['name'] for b in summary['brigades']))
            with store.transaction() as c:self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            store.catalog_upsert(admin,'sites',{'code':'LOCAL','name':'Сохранённая запись'})
            import_demo(target)
            self.assertTrue(any(s['code']=='LOCAL' for s in store.catalogs(admin)['sites']));store.close()
            other=Path(folder)/'existing';other.mkdir();db=other/'naryadai.db';db.write_bytes(b'existing')
            with self.assertRaises(ValueError):import_demo(other)
            self.assertEqual(db.read_bytes(),b'existing')

class DesktopConsolidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])
    def test_draft_score_and_catalog_pages(self):
        from PySide6.QtCore import QCoreApplication,QEvent
        from app.dialogs import SubmitReport,CreateTask,ReviewReport
        from app.windows import MainWindow
        from app.reference_dialogs import ReferenceEditor,NAMES
        from app.drafts import ReportDraft
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder,seed_demo=True);master=store.authenticate('master','1234','master');worker=store.authenticate('worker1','1234','worker')
            catalogs=store.catalogs(master);e=catalogs['equipment'][0];s=next(s for s in catalogs['sites'] if s['id']==e['site_id']);day=(date.today()+timedelta(days=30)).isoformat()
            tid=store.create_task(master,title='Проверить механизм',description='Проверить состояние и выполнить контрольный запуск',site=s['name'],equipment=e['name'],equipment_id=e['id'],priority='normal',kind='Плановая',duration=1,day=day,start=8,deadline=day+'T18:00',worker_id=worker['id'])
            store.transition(worker,tid,'accepted');store.transition(worker,tid,'inProgress')
            d=SubmitReport(store,worker,store.task(worker,tid),None);d.work.setPlainText('Проведён контрольный запуск механизма');d.result_text.setPlainText('Работа стабильна');d.add_material();d.persist_draft();d.reject()
            again=SubmitReport(store,worker,store.task(worker,tid),None);self.assertEqual(again.work.toPlainText(),d.work.toPlainText());self.assertEqual(again.table.rowCount(),1)
            again.table.selectRow(0);again.remove_material();self.assertEqual(ReportDraft(store,worker,tid).load()['materials'],[])
            again.save();self.assertFalse(ReportDraft(store,worker,tid).path.exists())
            report=store.latest_report(master,tid);review=ReviewReport(store,master,report,None);self.assertEqual(review.score.value(),-1);review.comment.setPlainText('Проверено');review.decide(True);self.assertEqual(store.task(master,tid)['status'],'submitted')
            review.score.setValue(0);review.decide(True);self.assertEqual(store.task(master,tid)['status'],'approved')
            create=CreateTask(store,master,None);self.assertEqual(create.priority.currentData(),'normal')
            for name in NAMES:
                items=store.catalogs(master)[name];editor=ReferenceEditor(store,master,name,None,items[0] if items else None);editor.close();editor.deleteLater()
            window=MainWindow(store,master);window.navigate('references');window.navigate('equipment');window.close()
            worker_window=MainWindow(store,worker);self.assertEqual(worker_window.task_filter,'mine');worker_window.close()
            for obj in (d,again,review,create,window,worker_window):obj.close();obj.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            self.qt.processEvents()
            store.close()

if __name__=='__main__':unittest.main(verbosity=2)
