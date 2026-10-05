"""Чат через настоящий HTTP: роли, история, обработчик и сбои доставки.
Ответ модели тестовый; настоящее подключение проверяется check_ai.bat на ПК.
"""
import json,sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_cloud import CloudChecks as CloudFixtures,DATABASE
from check_server import APP
from app.remote import RemoteStore
from app.windows import MainWindow
from server.chat import AdminChat


class ChatChecks(unittest.TestCase):
    setUp=CloudFixtures.setUp
    tearDown=CloudFixtures.tearDown
    def setup_admin(self):
        self.admin=RemoteStore(self.url);self.a=self.admin.authenticate('admin',self.password,'admin')
        self.addCleanup(self.admin._cache.cleanup)
        self.ai_settings.chat_workspace='naryadai-admin-chat'
        return self.admin.request('/api/chat')['conversation_id']
    def send(self,cid,text='Привет, помоги составить отчёт.',rid=None):
        return self.admin.request('/api/chat',{'conversation_id':cid,'request_id':rid or uuid.uuid4().hex,'message':text})
    def test_worker_round_trip_and_conversation_context(self):
        cid=self.setup_admin();first=self.send(cid)
        self.assertEqual(first['messages'][0]['status'],'queued')
        self.assertTrue(self.processor.run_once())
        history=self.admin.request('/api/chat')
        self.assertEqual(history['messages'][0]['answer'],'Связь работает. Чем помочь?')
        self.assertEqual(history['messages'][0]['model'],'Тестовая модель')
        self.assertTrue(history['online']);self.assertFalse(history['pending'])
        self.send(cid,'А что написать про материалы?');self.processor.run_once()
        first_payload=self.mock.payloads[0][2];second=self.mock.payloads[1][2]
        context=json.loads(second['message'].split('ДИАЛОГ:\n',1)[1])
        self.assertEqual(context['history'][0]['content'],'Привет, помоги составить отчёт.')
        self.assertEqual(context['history'][1]['content'],'Связь работает. Чем помочь?')
        self.assertNotEqual(first_payload['sessionId'],second['sessionId'])
        self.assertEqual(self.mock.payloads[0][0],'/api/v1/workspace/naryadai-admin-chat/chat')
        self.assertNotIn('Верни ТОЛЬКО один JSON',first_payload['message'])
        data=json.dumps(history,ensure_ascii=False)
        for secret in (self.key,'test-anything-key','lease_token'):self.assertNotIn(secret,data)
        self.assertNotIn('Привет, помоги',json.dumps(self.master.snapshot(),ensure_ascii=False))
    def test_only_admin_and_private_history(self):
        cid=self.setup_admin();self.send(cid)
        for client in (self.worker,self.master):
            with self.assertRaises(PermissionError):client.request('/api/chat')
            with self.assertRaises(PermissionError):client.request('/api/chat/new',{'request_id':uuid.uuid4().hex})
            with self.assertRaises(PermissionError):client.request('/api/chat',{'conversation_id':cid,'request_id':uuid.uuid4().hex,'message':'Нет прав'})
        self.app.state.store.add_user(self.a,'admin2','Другой админ','Поддержка','admin',self.password)
        other=RemoteStore(self.url);self.addCleanup(other._cache.cleanup);other.authenticate('admin2',self.password,'admin')
        self.assertEqual(other.request('/api/chat')['messages'],[])
        with self.assertRaises(PermissionError):other.request('/api/chat?conversation_id='+cid)
        with self.assertRaises(PermissionError):other.request('/api/chat',{'conversation_id':cid,'request_id':uuid.uuid4().hex,'message':'Чужой чат'})
        self.assertEqual(self.http.get('/api/chat').status_code,401)
    def test_idempotency_and_one_pending_message(self):
        cid=self.setup_admin();rid=uuid.uuid4().hex
        self.send(cid,'Один вопрос',rid);self.send(cid,'Один вопрос',rid)
        self.assertEqual(len(self.admin.request('/api/chat')['messages']),1)
        with self.assertRaises(ValueError):self.send(cid,'Второй вопрос')
        with self.assertRaises(PermissionError):self.send(cid,'Другой текст',rid)
        self.processor.run_once();self.send(cid,'Один вопрос',rid)
        self.assertEqual(len(self.admin.request('/api/chat')['messages']),1)
        job=self.processor.request('/api/ai/chat/claim',{})['job'];self.assertIsNone(job)
    def test_offline_disabled_timeout_and_stale_result(self):
        cid=self.setup_admin();self.send(cid)
        with self.app.state.store.transaction() as c:c.execute('UPDATE chat_requests SET created=1')
        state=self.admin.request('/api/chat');self.assertEqual(state['messages'][0]['status'],'failed')
        self.assertIn('ПК',state['messages'][0]['error'])
        self.settings.ai_enabled=False
        with self.assertRaises(ValueError):self.send(cid)
        self.settings.ai_enabled=True;self.send(cid)
        job=self.processor.request('/api/ai/chat/claim',{})['job']
        with self.app.state.store.transaction() as c:c.execute('UPDATE chat_requests SET lease_until=0 WHERE id=?',(job['id'],))
        state=self.admin.request('/api/chat');self.assertFalse(state['pending'])
        with self.assertRaises(ValueError):self.processor.request('/api/ai/chat/result/'+job['id'],{'lease':job['lease'],'answer':'Поздний ответ'})
        self.send(cid);job=self.processor.request('/api/ai/chat/claim',{})['job'];self.settings.ai_enabled=False
        with self.assertRaises(ValueError):self.processor.request('/api/ai/chat/result/'+job['id'],{'lease':job['lease'],'answer':'ИИ выключен'})
    def test_restart_result_retry_and_new_conversation(self):
        cid=self.setup_admin();self.send(cid);job=self.processor.request('/api/ai/chat/claim',{})['job']
        if DATABASE:
            from server.postgres import PostgresStore
            store=PostgresStore(self.folder/'restarted',self.settings,self.storage)
        else:
            from server.store import ServerStore
            store=ServerStore(self.settings.data_dir,self.settings)
        restarted=AdminChat(store,self.settings);self.assertIsNone(restarted.claim())
        restarted.result(job['id'],job['lease'],'Ответ после перезапуска','','Модель')
        restarted.result(job['id'],job['lease'],'Ответ после перезапуска','','Модель')
        self.assertEqual(restarted.history(self.a)['messages'][0]['answer'],'Ответ после перезапуска')
        nid=uuid.uuid4().hex;new=self.admin.request('/api/chat/new',{'request_id':nid})
        self.assertEqual(new['conversation_id'],nid);self.assertEqual(new['messages'],[])
        self.admin.request('/api/chat/new',{'request_id':nid});self.send(nid);self.processor.run_once()
        context=json.loads(self.mock.payloads[-1][2]['message'].split('ДИАЛОГ:\n',1)[1]);self.assertEqual(context['history'],[])
        self.assertEqual(len(self.admin.request('/api/chat?conversation_id='+cid)['messages']),1)
    def test_model_failure_and_missing_workspace(self):
        cid=self.setup_admin();self.send(cid);self.mock.mode='http_error';self.processor.run_once()
        state=self.admin.request('/api/chat');self.assertEqual(state['messages'][0]['status'],'failed');self.assertIn('HTTP 503',state['messages'][0]['error'])
        self.mock.mode='ok';self.ai_settings.chat_workspace='';self.send(cid);self.processor.run_once()
        self.assertIn('configure_server',self.admin.request('/api/chat')['messages'][-1]['error'])
        self.assertFalse(self.admin.request('/api/chat')['pending'])
    def test_windows_setup_creates_separate_workspaces(self):
        from tools import setup_server
        from server.config import Settings
        answers=iter([self.mock.url,'qwen test','нет','server_data','0'])
        with patch.object(setup_server,'ROOT',self.folder),patch('builtins.input',side_effect=lambda *a:next(answers)),patch('getpass.getpass',return_value='only-local-test-key'):
            setup_server.main()
        config=Settings.load(self.folder/'server_config.json')
        self.assertEqual(config.workspace,'naryadai');self.assertEqual(config.chat_workspace,'naryadai-admin-chat')
        self.assertEqual(config.model_label,'qwen test');self.assertFalse(config.send_images)
        self.assertEqual(len(self.mock.workspace_configs),2)
        self.assertNotIn('ТОЛЬКО один JSON',self.mock.workspace_configs[1]['openAiPrompt'])
    def test_gui_draft_survives_snapshot_and_send(self):
        cid=self.setup_admin();win=MainWindow(self.admin,self.a);win.show();win.navigate('ai_chat');widget=win.chat_widget
        def settle():
            deadline=time.monotonic()+5
            while widget._request or not widget.state:
                if time.monotonic()>deadline:self.fail('UI-запрос не завершился')
                APP.processEvents();time.sleep(.01)
            APP.processEvents()
        try:
            settle();widget.editor.setPlainText('Черновик вопроса');snapshot=self.admin.refresh_snapshot();win.refresh_signature='changed';win.remote_snapshot(snapshot)
            self.assertIs(win.chat_widget,widget);self.assertEqual(widget.editor.toPlainText(),'Черновик вопроса')
            widget.send();settle();self.assertEqual(widget.editor.toPlainText(),'');self.processor.run_once();widget.poll();settle()
            self.assertIn('Связь работает',widget.history.toPlainText())
            widget.editor.setPlainText('Оставить этот черновик');widget.poll();settle();self.assertEqual(widget.editor.toPlainText(),'Оставить этот черновик')
            for store,user in ((self.master,self.m),(self.worker,self.w)):
                other=MainWindow(store,user);self.assertNotIn('ai_chat',other.nav)
                other.refresh_timer.stop();other.close();other.deleteLater()
            win.grab().save(str(Path(__file__).resolve().parents[3]/'previews/admin-chat-1.4.png'))
        finally:
            win.refresh_timer.stop();widget.timer.stop();win.close();win.deleteLater();APP.processEvents()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ChatChecks))
    raise SystemExit(not result.wasSuccessful())
