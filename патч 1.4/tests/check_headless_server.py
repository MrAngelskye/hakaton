"""Проверка серверного окружения без Qt: HTTP, авторизация, фото и ручная оценка."""
import base64,sys,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fastapi.testclient import TestClient
from server.api import create_app
from server.config import Settings
from app.store import SITES

class HeadlessCheck(unittest.TestCase):
 def test_server_without_qt(self):
  with tempfile.TemporaryDirectory() as temp:
   folder=Path(temp);app=create_app(Settings(seed_demo=True,data_dir=folder/'data',ai_enabled=False))
   with TestClient(app) as client:
    m=client.post('/api/login',json={'username':'master','password':'1234','role':'master'}).json()
    w=client.post('/api/login',json={'username':'worker4','password':'1234','role':'worker'}).json()
    day=(date.today()+timedelta(days=1)).isoformat();count=0
    def call(session,method,*args,photos=None,**kwargs):
     nonlocal count
     count+=1;r=client.post('/api/call/'+method,headers={'Authorization':'Bearer '+session['token']},json={'request_id':'headless-request-%08d'%count,'args':list(args),'kwargs':kwargs,'photos':photos or []})
     self.assertEqual(r.status_code,200,r.text);return r.json()['result']
    tid=call(m,'create_task',title='Сервер без графики',description='Проверить конвейер и выполнить запуск.',site=SITES[0],equipment='Конвейер',priority='normal',kind='Плановая',duration=1,day=day,start=10,deadline=day+'T18:00',worker_id=w['user']['id'])
    call(w,'transition',tid,'inProgress');path=folder/'photo.png';Image.new('RGB',(32,32),'blue').save(path)
    photo={'name':path.name,'content':base64.b64encode(path.read_bytes()).decode()}
    rid=call(w,'submit',tid,work='Контакты очищены, контрольный запуск выполнен.',result='Работает',defect='Нет',hours=1,materials=[],photos=[photo])
    call(m,'review',rid,True,91,'Ручная проверка')
    reports=client.get('/api/snapshot',headers={'Authorization':'Bearer '+w['token']}).json()['reports']
    report=next(r for r in reports if r['id']==rid);self.assertEqual(report['score'],91)
    raw=client.get('/api/photos/'+report['photos'][0],headers={'Authorization':'Bearer '+w['token']})
    self.assertEqual(raw.content,path.read_bytes());self.assertEqual(raw.status_code,200)
   self.assertFalse(any(k.startswith('PySide6') for k in sys.modules))

if __name__=='__main__':unittest.main(verbosity=2)
