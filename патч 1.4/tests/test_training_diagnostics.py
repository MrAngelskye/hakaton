import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from server.training import requested, retrieve
from server.web_search import lookup
from tools.ai_diagnostics import diagnose, metrics


class Cursor:
    def __init__(self, value):self.value=value
    def fetchone(self):return self.value
    def fetchall(self):return self.value


class TrainingConnection:
    def __init__(self):self.queries=[]
    def execute(self,sql,args=()):
        self.queries.append((sql,args))
        if 'to_regclass' in sql:return Cursor({'relation':'naryadai_ai_training.work_orders'})
        if 'count(*)' in sql:return Cursor({'orders':500,'equipment':64,'materials':40})
        if 'dataset_metadata' in sql:return Cursor({'value':'{"start":"2026-07-08"}'})
        return Cursor([{'number':'SYN-2026-0001','title':'Проверка',
                       'required_actions':'["Осмотр"]','expected_materials':[],
                       'issued_at':datetime(2026,7,8,tzinfo=timezone.utc)}])


class TrainingTests(unittest.TestCase):
    def test_training_is_explicit_and_not_an_ordinary_order_query(self):
        for text in ('на учебном наборе','синтетические примеры','SYN-2026-0001'):
            self.assertTrue(requested(text))
        for text in ('Покажи наряды','Какие сотрудники свободны?','НР-19'):
            self.assertFalse(requested(text))

    def test_explicit_number_is_parameterized_and_no_answers_or_people_are_read(self):
        connection=TrainingConnection()
        result=retrieve(connection,'Учебный SYN-2026-0001',set())
        query,args=connection.queries[-1]
        self.assertEqual(args,('SYN-2026-0001',))
        self.assertIn('LIMIT 3',query)
        self.assertTrue(result['synthetic']);self.assertFalse(result['actual_images'])
        self.assertEqual(result['examples'][0]['required_actions'],['Осмотр'])
        json.dumps(result)
        for sql,_ in connection.queries:
            self.assertNotIn('answer_keys',sql);self.assertNotIn('people',sql)
            self.assertNotIn('closed_at',sql);self.assertNotIn('w.status',sql)

    def test_missing_private_schema_returns_unavailable(self):
        class Missing:
            def execute(self,*args):return Cursor({'relation':None})
        self.assertFalse(retrieve(Missing(),'Учебный пример',set())['available'])

    def test_training_never_triggers_external_search(self):
        with patch('server.web_search.urlopen') as network:
            for available in (True,False):
                result=lookup({'training':{'available':available},'web_allowed':True,
                               'public_query':'Как ремонтировать насос на учебном наборе'},'')
                self.assertEqual(result['status'],'not_used')
            network.assert_not_called()


class DiagnosticsTests(unittest.TestCase):
    def test_nanosecond_timings_and_zero_generation(self):
        result=metrics({'eval_duration':2_000_000_000,'eval_count':20,
                        'load_duration':1_000_000_000,'done':True},3)
        self.assertEqual(result['tokens_per_second'],10)
        self.assertEqual(result['load_seconds'],1)
        self.assertIsNone(metrics({},0)['tokens_per_second'])

    def test_short_tests_are_repeatable_without_configuration_or_cloud_auth(self):
        calls=[]
        def service(url,payload=None,timeout=20):
            calls.append((url,payload))
            if url.endswith('/health'):return {'ok':True}
            if url.endswith('/api/version'):return {'version':'test'}
            if url.endswith('/api/ps'):return {'models':[]}
            return {'done':True,'eval_count':20,'eval_duration':2_000_000_000}
        with patch('tools.ai_diagnostics.worker_config_paths',return_value=None), \
             patch('tools.ai_diagnostics.request_json',side_effect=service):
            result=diagnose('qwen3.5:9b','http://127.0.0.1:11434')
        self.assertIn('skipped',result['tests']['anythingllm'])
        payloads=[payload for url,payload in calls if url.endswith('/api/chat')]
        self.assertEqual(len(payloads),2)
        for payload in payloads:
            self.assertFalse(payload['think'])
            self.assertEqual(payload['options']['num_ctx'],4096)
            self.assertEqual(payload['options']['num_predict'],128)
            self.assertNotIn('attachments',payload)
        self.assertNotIn('password',json.dumps(result))

    def test_offline_ollama_is_reported_without_long_generation(self):
        def service(url,*args,**kwargs):
            if url.endswith('/health'):return {'ok':True}
            raise OSError('Сервис не отвечает.')
        with patch('tools.ai_diagnostics.worker_config_paths',return_value=None), \
             patch('tools.ai_diagnostics.request_json',side_effect=service):
            result=diagnose('qwen3.5:9b','http://127.0.0.1:11434')
        self.assertIn('ollama_error',result)
        self.assertNotIn('first',result['tests'])


if __name__=='__main__':unittest.main()
