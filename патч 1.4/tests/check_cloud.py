"""Облачный маршрут через настоящий HTTP, PostgreSQL и тестовый AnythingLLM.
TEST_DATABASE_URL допускает только локальную тестовую базу. Без него — SQLite.
Ответ тестового AnythingLLM проверяет контракт, а не качество модели.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,socket,sys,tempfile,threading,time,unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,uvicorn
from PySide6.QtGui import QImage,QColor
from app.remote import RemoteStore
from app.store import SITES
from server.config import Settings
from server.api import create_app
from server.anythingllm import AnythingLLM
from worker import Worker
from check_server import LocalAnythingAPI,VERDICT

DATABASE=os.environ.get('TEST_DATABASE_URL','')
if DATABASE:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(DATABASE).get('host') not in ('localhost','127.0.0.1'):
        raise RuntimeError('Тесты разрешены только на локальной тестовой PostgreSQL.')

class MemoryStorage:
    def __init__(self,*args):self.files={}
    def ensure_bucket(self):pass
    def upload(self,name,data):self.files[name]=data
    def download(self,name):return self.files[name]
    def delete(self,name):self.files.pop(name,None)

class CloudChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.mock=LocalAnythingAPI()
        self.password='Test-password-1.4' if DATABASE else '1234';self.key='local-test-worker-key-not-a-secret'*2
        self.storage=MemoryStorage()
        if DATABASE:
            with psycopg.connect(DATABASE) as c:
                c.execute('DROP SCHEMA IF EXISTS naryadai CASCADE')
                c.execute('CREATE TABLE IF NOT EXISTS public.unrelated_test(value text)')
                c.execute("INSERT INTO public.unrelated_test SELECT 'keep' WHERE NOT EXISTS(SELECT 1 FROM public.unrelated_test)")
        self.settings=Settings(data_dir=self.folder/'data',ai_mode='remote_worker',worker_token=self.key,
            database_url=DATABASE,bootstrap_password=self.password,offline_wait=120)
        with patch('server.storage.SupabaseStorage',return_value=self.storage):self.app=create_app(self.settings)
        self.socket=socket.socket();self.socket.bind(('127.0.0.1',0));self.url='http://127.0.0.1:'+str(self.socket.getsockname()[1])
        self.server=uvicorn.Server(uvicorn.Config(self.app,log_level='error',access_log=False))
        self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[self.socket]},daemon=True);self.thread.start()
        deadline=time.monotonic()+8
        while not self.server.started:
            if time.monotonic()>deadline:raise RuntimeError('Сервер не запустился')
            time.sleep(.01)
        self.http=httpx.Client(base_url=self.url,timeout=15,trust_env=False)
        self.master=RemoteStore(self.url);self.worker=RemoteStore(self.url);self.other=RemoteStore(self.url)
        self.m=self.master.authenticate('master',self.password,'master');self.w=self.worker.authenticate('worker4',self.password,'worker');self.o=self.other.authenticate('worker3',self.password,'worker')
        self.ai_settings=Settings(data_dir=self.folder,base_url=self.mock.url,api_key='test-anything-key',timeout=10,send_images=True,model_label='Тестовая модель')
        self.processor=Worker(self.url,self.key,AnythingLLM(self.ai_settings))
        self.day=(date.today()+timedelta(days=1)).isoformat()
    def tearDown(self):
        self.http.close();self.server.should_exit=True;self.thread.join(8);self.socket.close();self.mock.close()
        for client in (self.master,self.worker,self.other):client._cache.cleanup()
        self.temp.cleanup()
    def create(self,start=10):
        return self.master.create_task(self.m,title='Облачная проверка',description='Проверить конвейер и контрольный запуск.',site=SITES[0],equipment='Конвейер',priority='normal',kind='Плановая',duration=1,day=self.day,start=start,deadline=self.day+'T18:00',worker_id=self.w['id'])
    def submit(self,start=10,photo=False):
        tid=self.create(start);self.worker.transition(self.w,tid,'inProgress');sources=[]
        if photo:
            image=QImage(40,40,QImage.Format.Format_RGB32);image.fill(QColor('#665bdd'));path=self.folder/'image.png';image.save(str(path));sources=[str(path)]
        rid=self.worker.submit(self.w,tid,work='Контакты очищены, запуск выполнен.',result='Работает ровно.',defect='Нет',hours=1,materials=[],photo_sources=sources)
        return tid,rid
    def report(self,rid):
        self.master.refresh_snapshot();return next(r for r in self.master.reports(self.m) if r['id']==rid)
    def test_http_worker_photos_ai_and_manual_rating(self):
        tid,rid=self.submit(photo=True)
        self.assertEqual(self.report(rid)['status'],'aiPending')
        with self.assertRaises(ValueError):self.master.review(self.m,rid,True,90,'Рано')
        self.assertTrue(self.processor.run_once());r=self.report(rid)
        self.assertEqual(r['status'],'submitted');self.assertEqual(r['ai']['score'],78);self.assertIsNone(r['score'])
        self.assertEqual(len(self.mock.payloads[0][2]['attachments']),1)
        self.master.ensure_photos(r);self.assertTrue((self.master.photos/r['photos'][0]).is_file())
        with self.assertRaises(PermissionError):self.other.request('/api/photos/'+r['photos'][0],binary=True)
        self.master.review(self.m,rid,True,93,'Проверено мастером')
        self.assertEqual(self.report(rid)['score'],93);self.assertEqual(self.report(rid)['ai']['score'],78)
        self.assertFalse(self.processor.run_once())
        snapshot=json.dumps(self.master.snapshot())
        for secret in (self.key,'test-anything-key','lease_token','password_hash',DATABASE or 'never-a-value'):self.assertNotIn(secret,snapshot)
        if DATABASE:
            self.assertEqual(len(self.storage.files),1)
            from server.postgres import PostgresStore
            restarted=PostgresStore(self.folder/'restarted',self.settings,self.storage)
            self.assertEqual(next(r for r in restarted.reports(self.m) if r['id']==rid)['score'],93)
            with psycopg.connect(DATABASE) as c:
                self.assertEqual(c.execute('SELECT value FROM public.unrelated_test').fetchone()[0],'keep')
                self.assertTrue(all(r[0] for r in c.execute("SELECT rowsecurity FROM pg_tables WHERE schemaname='naryadai'")))
    def test_worker_authentication_and_stale_lease(self):
        _,rid=self.submit(photo=True)
        self.assertEqual(self.http.post('/api/ai/claim',json={}).status_code,401)
        self.assertEqual(self.http.post('/api/ai/claim',json={},headers={'Authorization':'Bearer '+self.master.token}).status_code,401)
        job=self.processor.request('/api/ai/claim',{})['job'];r=self.report(rid);name=r['photos'][0]
        route=f'/api/ai/photo/{rid}/{name}'
        self.assertEqual(self.http.get(route,headers={'Authorization':'Bearer '+self.key,'X-Job-Lease':'bad'}).status_code,400)
        invalid=self.http.post(f'/api/ai/result/{rid}',headers={'Authorization':'Bearer '+self.key},json={'lease':job['lease'],'result':{**VERDICT,'score':101}})
        self.assertEqual(invalid.status_code,400)
        with self.app.state.store.transaction() as c:c.execute('UPDATE ai_jobs SET lease_until=0 WHERE report_id=?',(rid,))
        self.assertEqual(self.report(rid)['ai']['status'],'failed')
        with self.assertRaises(ValueError):self.processor.request(f'/api/ai/result/{rid}',{'lease':job['lease'],'result':VERDICT})
        self.master.review(self.m,rid,True,88,'Ручная проверка');self.assertEqual(self.report(rid)['score'],88)
    def test_ai_failure_offline_and_switch_off(self):
        _,rid=self.submit();self.mock.mode='invalid';self.processor.run_once()
        self.assertEqual(self.report(rid)['ai']['status'],'failed');self.assertIn('JSON',self.report(rid)['ai']['error'])
        _,offline=self.submit(13)
        with self.app.state.store.transaction() as c:
            c.execute('UPDATE ai_worker_state SET last_seen=0');c.execute('UPDATE ai_jobs SET queued_at=1 WHERE report_id=?',(offline,))
        self.assertEqual(self.report(offline)['status'],'submitted');self.assertEqual(self.report(offline)['ai']['status'],'failed')
        self.settings.ai_enabled=False;_,disabled=self.submit(15)
        self.assertEqual(self.report(disabled)['ai']['status'],'skipped');self.assertEqual(self.report(disabled)['status'],'submitted')
        self.assertFalse(self.processor.run_once())
        self.settings.ai_enabled=True;_,active=self.submit(16)
        job=self.processor.request('/api/ai/claim',{})['job'];self.settings.ai_enabled=False
        self.assertEqual(self.report(active)['status'],'submitted')
        with self.assertRaises(ValueError):self.processor.request(f'/api/ai/result/{active}',{'lease':job['lease'],'result':VERDICT})
    def test_schedule_pause_and_atomic_conflicts(self):
        self.master.set_shift(self.m,self.w['id'],self.day,9,17)
        self.assertEqual(self.master.shift(self.m,self.w['id'],self.day),{'start':9.0,'end':17.0})
        tid=self.create();self.worker.transition(self.w,tid,'inProgress')
        self.worker.transition(self.w,tid,'paused','Нет материалов')
        pauses=self.worker.pauses(self.w,tid);self.assertEqual(pauses[-1]['reason'],'Нет материалов')
        with self.assertRaises(ValueError):self.create()
        self.worker.transition(self.w,tid,'inProgress')
        self.assertIsNotNone(self.worker.pauses(self.w,tid)[-1]['ended'])
    def test_queue_survives_restart_without_losing_lease(self):
        _,rid=self.submit();job=self.processor.request('/api/ai/claim',{})['job']
        from server.remote_jobs import RemoteJobs
        if DATABASE:
            from server.postgres import PostgresStore
            restarted=PostgresStore(self.folder/'restarted',self.settings,self.storage)
        else:
            from server.store import ServerStore
            restarted=ServerStore(self.settings.data_dir,self.settings)
        jobs=RemoteJobs(restarted,self.settings)
        self.assertIsNone(jobs.claim());jobs.result(rid,job['lease'],VERDICT,'','После рестарта')
        self.assertEqual(self.report(rid)['ai']['score'],78)

if __name__=='__main__':unittest.main(verbosity=2)
