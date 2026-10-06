"""Shared database retrieval, audited support, demo merge and manual materials."""
import json,unittest,uuid
from unittest.mock import patch
import test_case1 as fixtures
from server.demo_import import merge,read_demo_photo
from server.web_search import Results,lookup
from server.anythingllm import AnythingLLM
from test_case1 import image_data
import base64,tempfile

class NewFeatures(unittest.TestCase):
    setUp=fixtures.Case1Tests.setUp
    tearDown=fixtures.Case1Tests.tearDown
    login=fixtures.Case1Tests.login
    rpc=fixtures.Case1Tests.rpc
    task_fields=fixtures.Case1Tests.task_fields
    create=fixtures.Case1Tests.create
    start=fixtures.Case1Tests.start
    submit=fixtures.Case1Tests.submit
    def command(self,text,rid=None):
        return self.client.post('/api/admin/command',headers=self.admin,json={'command':text,'request_id':rid or uuid.uuid4().hex})
    def test_console_roles_idempotence_and_persistent_settings(self):
        self.assertEqual(self.client.get('/api/admin/monitor',headers=self.worker).status_code,403)
        self.assertEqual(self.client.post('/api/admin/command',headers=self.master,json={'command':'/ai on','request_id':uuid.uuid4().hex}).status_code,403)
        rid=uuid.uuid4().hex
        self.assertEqual(self.command('/ai on',rid).status_code,200)
        self.assertEqual(self.command('/ai on',rid).status_code,200)
        self.assertEqual(self.command('/ai off',rid).status_code,403)
        with self.store.transaction() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM support_audit WHERE detail='/ai on'").fetchone()['n'],1)
        self.settings.ai_enabled=False;self.app.state.control.refresh();self.assertTrue(self.settings.ai_enabled)
        self.assertEqual(self.command('/help').status_code,200)
        self.assertEqual(self.client.get('/api/admin/monitor',headers=self.admin).status_code,200)
    def test_documents_live_records_missing_ids_and_materials(self):
        tid=self.create();self.start(tid)
        rid=self.submit(tid,materials=[{'name':'Введённая вручную деталь','quantity':2,'unit':'шт.','price':7}])
        report=self.store.latest_report(self.a,tid);self.assertEqual(report['materials'][0]['name'],'Введённая вручную деталь')
        payload={'title':'Проверка подшипника','body':'Подшипник проверяют на люфт и нагрев. Остановите оборудование согласно утверждённой процедуре.','request_id':uuid.uuid4().hex}
        self.assertEqual(self.client.post('/api/knowledge',headers=self.worker,json=payload).status_code,403)
        self.assertEqual(self.client.post('/api/knowledge',headers=self.admin,json=payload).status_code,200)
        facts=self.app.state.knowledge.retrieve(self.a,'Как проверить подшипник?')
        self.assertTrue(facts['documents_found'])
        facts=self.app.state.knowledge.retrieve(self.a,'Наряд '+str(tid))
        self.assertEqual(facts['records'][0]['id'],tid);self.assertTrue(facts['database_found'])
        facts=self.app.state.knowledge.retrieve(self.a,'Наряд 987654321')
        self.assertEqual(facts['missing_task_ids'],[987654321]);self.assertFalse(facts['database_found'])
    def test_demo_merge_preserves_credentials_idempotent_photos(self):
        with self.store.transaction() as c:
            before=[dict(r) for r in c.execute('SELECT * FROM users')]
            counts={t:c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('tasks','reports')}
        result=merge(self.store,self.a,self.app.state.control)
        self.assertEqual(result['tasks'],608);self.assertEqual(result['reports'],655)
        self.assertEqual(merge(self.store,self.a,self.app.state.control),result)
        with self.store.transaction() as c:
            after=[dict(r) for r in c.execute('SELECT * FROM users WHERE id<?',(result['base'],))]
            self.assertEqual(before,after)
            for t in counts:self.assertEqual(c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'],counts[t]+result[t])
            photo=c.execute("SELECT object_key FROM task_photos WHERE object_key LIKE 'demo_%' LIMIT 1").fetchone()['object_key']
            if self.settings.database_url:
                self.assertEqual(c.execute('SELECT count(*) AS n FROM reports r LEFT JOIN tasks t ON t.id=r.task_id WHERE t.id IS NULL').fetchone()['n'],0)
            else:self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        self.assertTrue(read_demo_photo(photo).startswith(b'\xff\xd8'))
    def test_external_search_does_not_send_internal_questions(self):
        with patch('server.web_search.urlopen') as network:
            self.assertEqual(lookup({'web_allowed':True,'public_query':'Наряд 12','requested_task_ids':[12]},'')['status'],'not_used')
            self.assertEqual(lookup({'web_allowed':True,'public_query':'Как починить насос [номер]'},'')['status'],'private_query_blocked')
            network.assert_not_called()
        parser=Results();parser.feed('<a class="result__a" href="https://example.org/manual">Manual</a><a class="result__snippet">Repair information</a>')
        self.assertEqual(parser.items[0]['snippet'],'Repair information')

    def test_vision_attachments_and_grounded_report_payload(self):
        tid=self.create();self.start(tid);rid=self.submit(tid,photos=[image_data()])
        with self.store.transaction() as c:
            task,report=self.store.ai_context(c,self.store.task(self.a,tid),self.store.latest_report(self.a,tid))
        ai=AnythingLLM(self.settings);self.settings.send_images=True
        result={'score':85,'verdict':'acceptable','summary':'Проверка','findings':[], 'criteria':{'description':20,'matching':20,'verification':25,'materials_time':20}}
        with patch.object(ai,'request',return_value={'textResponse':json.dumps(result)}) as network:
            self.assertEqual(ai.review(task,report,self.store.photos)['score'],85)
            body=network.call_args.args[1];self.assertEqual(len(body['attachments']),1)
            self.assertEqual(body['attachments'][0]['mime'],'image/jpeg')
            self.assertTrue(body['attachments'][0]['contentString'].startswith('data:image/jpeg;base64,'))
            self.assertIn('photos_sent_to_model',body['message']);self.assertIn('historical_context',body['message'])
