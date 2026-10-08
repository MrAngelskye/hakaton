"""Native Android client contract against an isolated real Python API/SQLite DB."""
import base64
from datetime import date, timedelta
import io
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fastapi.testclient import TestClient
from server.api import create_app
from server.config import Settings

class FlutterContract(unittest.TestCase):
    def test_employee_master_cycle_and_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(seed_demo=True, data_dir=Path(temporary), api_key='', ai_enabled=False)
            with TestClient(create_app(settings)) as client:
                def login(name, role):
                    response = client.post('/api/login', json={'username':name,'password':'1234','role':role})
                    self.assertEqual(response.status_code, 200, response.text)
                    return response.json()
                master = login('master', 'master');worker = login('worker4', 'worker')
                mh = {'Authorization':'Bearer '+master['token']};wh = {'Authorization':'Bearer '+worker['token']}
                def call(method, args=None, kwargs=None, photos=None, who=mh, request_id=None):
                    payload = {'args':args or [],'kwargs':kwargs or {},'photos':photos or [],'request_id':request_id or uuid.uuid4().hex}
                    response = client.post('/api/call/'+method, headers=who, json=payload)
                    self.assertEqual(response.status_code, 200, response.text)
                    return response.json()['result']
                refs = client.get('/api/catalogs', headers=mh).json();equipment = refs['equipment'][0]
                site = next(item for item in refs['sites'] if item['id']==equipment['site_id'])
                day = (date.today()+timedelta(days=1)).isoformat()
                call('set_shift', [worker['user']['id'],day,8,18])
                tid = call('create_task', kwargs={'title':'Проверка мобильного цикла','description':'Осмотреть соединения и записать результаты контрольной проверки.','site':site['name'],'equipment':equipment['name'],'site_id':site['id'],'equipment_id':equipment['id'],'priority':'normal','kind':'Внеплановая','duration':1,'day':day,'start':None,'deadline':day+'T18:00:00','worker_id':None,'complexity':1})
                call('claim', [tid,day,9], who=wh);call('transition', [tid,'inProgress'], who=wh)
                image = io.BytesIO();Image.new('RGB',(80,80),(20,70,130)).save(image,format='JPEG')
                photos = [{'name':'after.jpg','content':base64.b64encode(image.getvalue()).decode('ascii')}]
                report = {'work':'Проверил крепления и записал наблюдения по карте работ.','result':'Контрольная проверка завершена, замечаний не обнаружено.','defect':refs['defect_codes'][0]['code'],'hours':1,'materials':[]}
                request_id = uuid.uuid4().hex
                rid = call('submit',[tid],report,photos,wh,request_id)
                self.assertEqual(call('submit',[tid],report,photos,wh,request_id), rid)
                call('review',[rid,True,90,'Работа принята после проверки мастером.'])
                snapshot = client.get('/api/snapshot?day='+day,headers=wh).json()
                self.assertEqual(next(t for t in snapshot['tasks'] if t['id']==tid)['status'],'approved')
                self.assertEqual(len([r for r in snapshot['reports'] if r['task_id']==tid]),1)
                forbidden = client.post('/api/call/review',headers=wh,json={'args':[rid,True,100,'Попытка самоприёмки'],'kwargs':{},'request_id':uuid.uuid4().hex})
                self.assertEqual(forbidden.status_code,403)

if __name__=='__main__':
    unittest.main()
