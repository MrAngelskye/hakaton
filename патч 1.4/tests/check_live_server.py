"""Настоящий процесс uvicorn, HTTP-клиенты и тестовый HTTP API AnythingLLM.
Здесь проверяется подключение, а не качество локальной модели.
"""
import json,socket,subprocess,sys,tempfile,threading,time,unittest
from datetime import date,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.remote import RemoteStore
from app.store import SITES
from PySide6.QtGui import QImage,QColor

class LiveServerCheck(unittest.TestCase):
    def test_two_clients_over_http(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.path=='/api/v1/workspace/naryadai/chat'
                assert self.headers['Authorization']=='Bearer local-test-only'
                assert payload['mode']=='chat'
                assert len(payload['attachments'])==1
                result={'score':84,'verdict':'acceptable','summary':'В отчёте описан контрольный запуск. Мастер должен подтвердить результат.',
                        'findings':[],'criteria':{'description':22,'matching':22,'verification':25,'materials_time':15}}
                raw=json.dumps({'type':'textResponse','textResponse':json.dumps(result,ensure_ascii=False),'error':None}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        ai=ThreadingHTTPServer(('127.0.0.1',0),Handler);ai_thread=threading.Thread(target=ai.serve_forever,daemon=True);ai_thread.start()
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            cfg={'data_dir':str(folder/'data'),'base_url':f'http://127.0.0.1:{ai.server_port}','api_key':'local-test-only','workspace':'naryadai','host':'127.0.0.1','port':port,'send_images':True}
            config=folder/'server.json';config.write_text(json.dumps(cfg),encoding='utf-8');clients=[]
            with (folder/'server.log').open('w') as log:
                process=subprocess.Popen([sys.executable,str(ROOT/'run_server.py'),'--config',str(config)],cwd=ROOT,stdout=log,stderr=log)
                try:
                    url=f'http://127.0.0.1:{port}';deadline=time.monotonic()+12
                    while True:
                        try:master=RemoteStore(url);clients.append(master);break
                        except OSError:
                            if time.monotonic()>deadline or process.poll() is not None:self.fail('Сервер не запустился: '+(folder/'server.log').read_text())
                            time.sleep(.05)
                    worker=RemoteStore(url);clients.append(worker)
                    m=master.authenticate('master','1234','master');w=worker.authenticate('worker4','1234','worker')
                    day=(date.today()+timedelta(days=1)).isoformat()
                    tid=master.create_task(m,title='Наряд через настоящий HTTP',description='Осмотреть привод и провести контрольный запуск.',site=SITES[0],equipment='Стенд',priority='normal',kind='Плановая',duration=1,day=day,start=10,deadline=day+'T18:00',worker_id=w['id'])
                    self.assertEqual(worker.task(w,tid)['status'],'planned')
                    worker.transition(w,tid,'inProgress');worker.transition(w,tid,'paused',reason='Ждём комплектующие для контрольного запуска')
                    self.assertIn('Ждём комплектующие',master.pauses(m,tid)[0]['reason'])
                    worker.transition(w,tid,'inProgress')
                    photo=folder/'result.png';image=QImage(40,40,QImage.Format.Format_RGB32);image.fill(QColor('#5050de'));self.assertTrue(image.save(str(photo)))
                    rid=worker.submit(w,tid,work='Осмотрен привод. Контрольный запуск 10 минут.',result='Замечаний не обнаружено.',defect='Нет',hours=1,materials=[],photo_sources=[str(photo)])
                    deadline=time.monotonic()+6
                    while True:
                        master.refresh_snapshot();report=master.latest_report(m,tid)
                        if report['status']=='submitted':break
                        if time.monotonic()>deadline:self.fail('Отчёт не дошёл до мастера')
                        time.sleep(.03)
                    self.assertEqual(report['ai']['score'],84);self.assertIsNone(report['score'])
                    master.ensure_photos(report);self.assertEqual(QImage(str(master.photos/report['photos'][0])).width(),40)
                    master.review(m,rid,True,95,'Проверено мастером на месте.')
                    worker.refresh_snapshot();report=worker.latest_report(w,tid)
                    self.assertEqual(report['score'],95);self.assertEqual(report['ai']['score'],84)
                    self.assertEqual(worker.task(w,tid)['status'],'approved')
                finally:
                    for client in clients:client.logout();client._cache.cleanup()
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    ai.shutdown();ai.server_close();ai_thread.join(timeout=2)

if __name__=='__main__':unittest.main(verbosity=2)
