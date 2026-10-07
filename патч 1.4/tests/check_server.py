"""Сетевой поток и реальный HTTP-контракт AnythingLLM через локальный тестовый API.
Тестовый API не является проверкой качества настоящей модели.
Запуск: python tests/check_server.py
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import base64,json,sys,tempfile,threading,time,unittest
from datetime import date,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from PySide6.QtCore import QDate
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication,QLabel
from app.remote import RemoteStore
from app.store import SITES
from app.widgets import ROOT
from app.windows import MainWindow
from app.dialogs import ReviewReport,SubmitReport
from server.config import Settings
from server.api import create_app
from server.anythingllm import parse_verdict,AIError
from tools.setup_server import choose_workspace
from unittest.mock import patch

APP=QApplication.instance() or QApplication([])
from app.theme import apply_theme
APP.setStyle('Fusion');apply_theme(APP)
VERDICT={'score':78,'verdict':'needs_clarification','summary':'Описание понятное, но нужно уточнить нагрузку при запуске.',
         'findings':['Укажите нагрузку при контрольной проверке.'],
         'criteria':{'description':20,'matching':20,'verification':22,'materials_time':16}}

class LocalAnythingAPI:
    def __init__(self):
        self.payloads=[];self.workspace_configs=[];self.allow=threading.Event();self.allow.set();self.started=threading.Event();self.mode='ok'
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,obj,code=200):
                body=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):self.send({'workspaces':[{'name':'NaryadAI','slug':'naryadai'}]} if self.path.endswith('/workspaces') else {'workspace':[{'slug':'naryadai'}]})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path.endswith('/workspace/new'):
                    owner.workspace_configs.append(body);self.send({'workspace':{'slug':'naryadai-admin-chat' if 'чат' in body.get('name','') else 'naryadai'}});return
                owner.payloads.append((self.path,self.headers.get('Authorization'),body))
                owner.started.set();owner.allow.wait(5)
                if owner.mode=='http_error':self.send({'error':'not available'},503)
                else:self.send({'type':'textResponse','textResponse':('Связь работает. Чем помочь?' if '/naryadai-admin-chat/chat' in self.path else json.dumps(VERDICT,ensure_ascii=False)) if owner.mode=='ok' else 'Я не вернул JSON','error':None})
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.url=f'http://127.0.0.1:{self.http.server_port}'
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def close(self):self.allow.set();self.http.shutdown();self.http.server_close();self.thread.join()

class ServerChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.mock=LocalAnythingAPI()
        self.settings=Settings(seed_demo=True,data_dir=self.folder/'data',base_url=self.mock.url,api_key='test-server-only-key',workspace='naryadai',timeout=10,model_label='Тестовый ответ HTTP')
        self.app=create_app(self.settings);self.client=TestClient(self.app);self.client.__enter__();self.windows=[]
        def transport(path,payload,token,binary):
            r=self.client.request('POST' if payload is not None else 'GET',path,json=payload,headers={'Authorization':'Bearer '+token} if token else {})
            if r.status_code>=400:
                msg=r.json().get('detail','error')
                if r.status_code in (401,403):raise PermissionError(msg)
                raise ValueError(msg)
            return r.content if binary else r.json()
        self.worker=RemoteStore('http://testserver',transport=transport);self.master=RemoteStore('http://testserver',transport=transport);self.other=RemoteStore('http://testserver',transport=transport)
        self.w=self.worker.authenticate('worker4','1234','worker');self.m=self.master.authenticate('master','1234','master');self.o=self.other.authenticate('worker3','1234','worker')
        self.day=(date.today()+timedelta(days=1)).isoformat()
    def tearDown(self):
        self.mock.allow.set()
        for w in self.windows:w.refresh_timer.stop() if hasattr(w,'refresh_timer') else None;w.close()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and any(getattr(w,'_snapshot_loader',None) and w._snapshot_loader.isRunning() for w in self.windows):APP.processEvents();time.sleep(.01)
        for w in self.windows:w.deleteLater()
        APP.processEvents();self.client.__exit__(None,None,None);self.mock.close()
        for store in (self.worker,self.master,self.other):store._cache.cleanup()
        self.temp.cleanup()
    def create(self,start=10):
        return self.master.create_task(self.m,title='Совместный тест конвейера',description='Проверить контакты и выполнить контрольный запуск.',site=SITES[0],equipment='Конвейер 1',priority='normal',kind='Плановая',duration=1,day=self.day,start=start,deadline=self.day+'T18:00',worker_id=self.w['id'])
    def submit(self,tid,photos=None):
        self.worker.transition(self.w,tid,'inProgress')
        return self.worker.submit(self.w,tid,work='Очищены контакты и проведён контрольный запуск.',result='Конвейер работает ровно',defect='Нет',hours=1,materials=[],photo_sources=photos or [])
    def await_report(self,rid,status='submitted'):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            self.master.refresh_snapshot();r=next(r for r in self.master.reports(self.m) if r['id']==rid)
            if r['status']==status:return r
            time.sleep(.02)
        self.fail('Очередь ИИ не завершилась')
    def test_two_clients_ai_then_master_and_rating(self):
        self.mock.allow.clear();tid=self.create();self.worker.refresh_snapshot();self.assertEqual(self.worker.task(self.w,tid)['title'],'Совместный тест конвейера')
        rid=self.submit(tid);self.assertTrue(self.mock.started.wait(4))
        self.master.refresh_snapshot();r=self.master.latest_report(self.m,tid)
        self.assertEqual(r['status'],'aiPending');self.assertIsNone(r['score'])
        with self.assertRaises(ValueError):self.master.review(self.m,rid,True,90,'До завершения проверки')
        self.mock.allow.set();r=self.await_report(rid)
        self.assertEqual(r['ai']['score'],78);self.assertIsNone(r['score'])
        with self.assertRaises(PermissionError):self.worker.review(self.w,rid,True,90,'Нет прав')
        self.master.review(self.m,rid,True,92,'Проверка описана, работа принята')
        self.worker.refresh_snapshot();final=self.worker.latest_report(self.w,tid)
        self.assertEqual(final['score'],92);self.assertEqual(final['ai']['score'],78)
        rating=next(p for p in self.master.metrics(self.m) if p['id']==self.w['id'])
        self.assertAlmostEqual(rating['score'],(89+93+92)/3)
        path,auth,payload=self.mock.payloads[0]
        self.assertEqual(path,'/api/v1/workspace/naryadai/chat');self.assertEqual(auth,'Bearer test-server-only-key');self.assertEqual(payload['mode'],'chat')
        self.assertTrue(payload['sessionId'].startswith('naryadai-'));self.assertIn('Совместный тест',payload['message'])
        self.assertNotIn('test-server-only-key',json.dumps(self.master.snapshot()))
    def test_failure_routes_to_human_and_off_bypasses(self):
        self.mock.mode='invalid';rid=self.submit(self.create());r=self.await_report(rid)
        self.assertEqual(r['ai']['status'],'failed');self.assertIsNone(r['ai']['score']);self.assertIn('JSON',r['ai']['error'])
        self.master.review(self.m,rid,False,None,'Уточните проверку')
        self.settings.ai_enabled=False;count=len(self.mock.payloads);tid=self.create(start=13);rid2=self.submit(tid)
        r2=self.await_report(rid2);self.assertEqual(r2['ai']['status'],'skipped');self.assertEqual(len(self.mock.payloads),count)
        self.mock.mode='http_error';self.settings.ai_enabled=True;rid3=self.submit(self.create(start=15));r3=self.await_report(rid3)
        self.assertEqual(r3['ai']['status'],'failed');self.assertIn('HTTP 503',r3['ai']['error'])
    def test_network_photos_permissions_and_rework(self):
        image=QImage(40,40,QImage.Format.Format_RGB32);image.fill(QColor('#4b50dc'));photo=self.folder/'result.png';image.save(str(photo))
        self.settings.send_images=True;tid=self.create();rid=self.submit(tid,[str(photo)]);r=self.await_report(rid)
        self.assertEqual(len(self.mock.payloads[0][2]['attachments']),1)
        name=r['photos'][0];self.master.ensure_photos(r);self.assertTrue((self.master.photos/name).is_file())
        self.assertTrue(QImage(str(self.master.photos/name)).width()==40)
        with self.assertRaises(PermissionError):self.other.request('/api/photos/'+name,binary=True)
        self.assertEqual(self.client.get('/api/photos/'+name).status_code,401)
        self.master.review(self.m,rid,False,None,'Уточните нагрузку')
        parent=MainWindow(self.worker,self.w);self.windows.append(parent)
        d=SubmitReport(self.worker,self.w,self.worker.task(self.w,tid),parent);self.windows.append(d)
        self.assertEqual(len(d.photo_sources),1);d.result_text.setPlainText('Контрольная проверка с нагрузкой 50% пройдена');d.save()
        rid2=max(r['id'] for r in self.app.state.store.reports(self.m));r2=self.await_report(rid2)
        self.assertEqual(len(r2['photos']),1)
        old=next(r for r in self.app.state.store.reports(self.m) if r['id']==rid);self.assertEqual(old['status'],'superseded')
    def test_server_rejects_role_forgery_and_repeated_creation(self):
        tid=self.create()
        body={'args':[tid,'inProgress'],'kwargs':{'actor':{'id':1,'role':'admin'}},'request_id':'1234567890abcdef','photos':[]}
        r=self.client.post('/api/call/transition',json=body,headers={'Authorization':'Bearer '+self.worker.token});self.assertEqual(r.status_code,400)
        self.assertEqual(self.client.post('/api/call/transaction',json=body,headers={'Authorization':'Bearer '+self.worker.token}).status_code,404)
        r=self.client.get('/api/snapshot',headers={'Authorization':'Bearer invalid'});self.assertEqual(r.status_code,401)
        kwargs=dict(title='Повторный запрос создания',description='Проверить контакты и результат работы.',site=SITES[0],equipment='Стенд 2',priority='normal',kind='Плановая',duration=1,day=self.day,start=14,deadline=self.day+'T18:00',worker_id=None)
        body={'args':[],'kwargs':kwargs,'request_id':'same-create-request-id','photos':[]};headers={'Authorization':'Bearer '+self.master.token}
        a=self.client.post('/api/call/create_task',json=body,headers=headers).json();b=self.client.post('/api/call/create_task',json=body,headers=headers).json();self.assertEqual(a,b)
        with self.assertRaises(ValueError):self.master.create_task(self.m,**{**kwargs,'worker_id':self.w['id'],'start':10})
        self.master.logout();self.assertEqual(self.client.get('/api/snapshot',headers=headers).status_code,401)
        admin=self.client.post('/api/login',json={'username':'admin','password':'1234','role':'admin'}).json()
        body={'args':[],'kwargs':{'uid':self.w['id'],'password':'5678'},'request_id':'reset-password-keyword-args','photos':[]}
        response=self.client.post('/api/call/reset_password',json=body,headers={'Authorization':'Bearer '+admin['token']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/snapshot',headers={'Authorization':'Bearer '+self.worker.token}).status_code,401)
        self.assertEqual(self.worker.authenticate('worker4','5678','worker')['id'],self.w['id'])
    def test_remote_gui_updates_without_search_focus_loss(self):
        win=MainWindow(self.worker,self.w);self.windows.append(win);win.show();APP.processEvents();win.task_filter='mine';win.navigate('tasks')
        win.search.setText('Совместный');win.search.setFocus();APP.processEvents()
        tid=self.create();win.refresh_if_idle()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not any(t['id']==tid for t in win.tasks):APP.processEvents();time.sleep(.01)
        self.assertTrue(any(t['id']==tid for t in win.tasks));self.assertEqual(win.search.text(),'Совместный')
        rid=self.submit(tid);r=self.await_report(rid)
        master_win=MainWindow(self.master,self.m);self.windows.append(master_win);master_win.show();APP.processEvents()
        d=ReviewReport(self.master,self.m,r,master_win);self.windows.append(d);d.show();APP.processEvents()
        self.assertTrue(any('Оценка ИИ: 78' in l.text() for l in d.findChildren(QLabel)));self.assertEqual(d.score.value(),78)
        self.assertIsNone(self.worker.latest_report(self.w,tid)['score'])
        d.score.setValue(96);d.comment.setPlainText('Проверено мастером');d.decide(True)
        self.worker.refresh_snapshot();self.assertEqual(self.worker.latest_report(self.w,tid)['score'],96)
    def test_json_validation(self):
        self.assertEqual(parse_verdict('<think>reasoning</think>\n```json\n'+json.dumps(VERDICT)+'\n```')['score'],78)
        for value in ({**VERDICT,'score':True},{**VERDICT,'score':101},{**VERDICT,'score':77},{**VERDICT,'findings':['x']*21}):
            with self.assertRaises(AIError):parse_verdict(json.dumps(value))
    def test_workspace_configuration(self):
        with patch('builtins.input',return_value='0'):
            self.assertEqual(choose_workspace(self.app.state.provider),'naryadai')
        self.assertEqual(self.mock.workspace_configs[0]['chatMode'],'chat')
        self.assertIn('Окончательное решение',self.mock.workspace_configs[0]['openAiPrompt'])
        with patch('builtins.input',return_value='1'):
            self.assertEqual(choose_workspace(self.app.state.provider),'naryadai')
        self.assertEqual(len(self.mock.workspace_configs),1)

if __name__=='__main__':unittest.main(verbosity=2)
