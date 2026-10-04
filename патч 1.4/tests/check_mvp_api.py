"""HTTP contracts for the mobile MVP: roles, retries, original photos, private data.

Uses a disposable SQLite database and generated photos; never contacts a model,
Supabase or an installed production application.
"""
import base64
import io
import json
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fastapi.testclient import TestClient
from app.domain import company_time
from server.api import create_app
from server.config import Settings


class MVPApiChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(data_dir=Path(self.temp.name) / 'data', ai_enabled=False))
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.sessions = {}
        for username, role in [('master', 'master'), ('admin', 'admin'), ('worker1', 'worker'), ('worker2', 'worker')]:
            reply = self.client.post('/api/login', json={'username': username, 'password': '1234', 'role': role})
            self.assertEqual(reply.status_code, 200, reply.text)
            self.sessions[username] = reply.json()
        self.day = (company_time().date() + timedelta(days=1)).isoformat()
        refs = self.rpc('master', 'references')
        self.site = refs['sites'][0]
        self.equipment = next(e for e in refs['equipment'] if e['site_id'] == self.site['id'])

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def headers(self, username):
        return {'Authorization': 'Bearer ' + self.sessions[username]['token']}

    def rpc_response(self, username, method, *args, request_id=None, photos=None, **kwargs):
        return self.client.post('/api/call/' + method, headers=self.headers(username), json={
            'request_id': request_id or uuid.uuid4().hex, 'args': list(args), 'kwargs': kwargs, 'photos': photos or []})

    def rpc(self, username, method, *args, **kwargs):
        reply = self.rpc_response(username, method, *args, **kwargs)
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()['result']

    def snapshot(self, username):
        response = self.client.get('/api/snapshot', headers=self.headers(username), params={'day': self.day})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def task_body(self, username='worker1', **overrides):
        body = dict(title='Проверить привод конвейера', description='Осмотреть привод и выполнить контрольный запуск.',
                    site=self.site['name'], equipment=self.equipment['name'], priority='high', kind='Внеплановая',
                    duration=1, day=self.day, start=10, deadline=self.day+'T18:00',
                    worker_id=self.sessions[username]['user']['id'], issued=True)
        body.update(overrides)
        return body

    def issue(self, username='worker1', **overrides):
        return self.rpc('master', 'create_task', **self.task_body(username, **overrides))

    def start(self, username, tid):
        self.rpc(username, 'transition', tid, 'accepted')
        self.rpc(username, 'transition', tid, 'inProgress')

    def photo(self):
        buffer = io.BytesIO()
        image = Image.new('RGB', (96, 96), 'blue')
        exif = Image.Exif()
        exif[36867] = '2026:01:01 09:00:00'
        exif[36881] = '+05:00'
        image.save(buffer, 'JPEG', exif=exif)
        return {'name': 'original.jpg', 'content': base64.b64encode(buffer.getvalue()).decode()}

    def submit(self, username, tid, photos=None, **overrides):
        body = dict(work='Контакты очищены, выполнен контрольный запуск.', result='Запуск выполнен, шум отсутствует.',
                    defect='D-03', hours=1, materials=[])
        body.update(overrides)
        return self.rpc(username, 'submit', tid, photos=[self.photo()] if photos is None else photos, **body)

    def test_issued_flow_roundtrip_and_master_review(self):
        tid = self.issue()
        self.assertEqual(self.rpc('worker1', 'task', tid)['status'], 'issued')
        self.start('worker1', tid)
        self.rpc('worker1', 'transition', tid, 'paused', reason='Ожидание запасного датчика')
        self.rpc('worker1', 'transition', tid, 'inProgress')
        rid = self.submit('worker1', tid)
        report = next(r for r in self.snapshot('worker1')['reports'] if r['id'] == rid)
        self.assertEqual(report['status'], 'submitted')
        self.assertEqual(report['ai']['status'], 'skipped')
        self.assertIsInstance(report['checks'], list)
        self.rpc('master', 'review', rid, True, 91, 'Результат контрольного запуска проверен')
        self.assertEqual(self.rpc('worker1', 'task', tid)['status'], 'approved')
        history = self.rpc('master', 'equipment_history', self.equipment['name'])
        item = next(t for t in history['tasks'] if t['id'] == tid)
        self.assertTrue(item['completed_at'])
        self.assertTrue(item['timing_recorded'])
        self.assertEqual(len(item['pauses']), 1)
        self.assertTrue(item['pauses'][0]['ended'])

    def test_worker_cannot_issue_reassign_or_change_reference_settings(self):
        tid = self.issue()
        calls = [
            ('create_task', (), self.task_body('worker2')),
            ('reassign_task', (tid, self.sessions['worker2']['user']['id'], self.day, 10, 'Передача работы'), {}),
            ('save_reference', ('materials', {'name': 'Проверочный материал', 'unit': 'шт.', 'price': 0}), {}),
            ('delete_reference', ('equipment', self.equipment['id']), {}),
            ('set_notification_settings', (), {'accept_minutes': 5}),
            ('attention', (), {}),
        ]
        for method, args, kwargs in calls:
            with self.subTest(method=method):
                response = self.rpc_response('worker1', method, *args, **kwargs)
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.rpc('master', 'task', tid)['worker_id'], self.sessions['worker1']['user']['id'])

    def test_reference_admin_crud_and_site_equipment_link(self):
        item = self.rpc('admin', 'save_reference', 'materials', {'name': 'Тестовый фильтр', 'unit': 'шт.', 'price': 0})
        self.assertIn(item['id'], [m['id'] for m in self.rpc('worker1', 'references', 'materials')])
        self.rpc('admin', 'delete_reference', 'materials', item['id'])
        self.assertNotIn(item['id'], [m['id'] for m in self.rpc('worker1', 'references', 'materials')])
        self.assertIn(item['id'], [m['id'] for m in self.rpc('admin', 'references', 'materials')])
        response = self.rpc_response('master', 'save_reference', 'sites', {'name': 'Подмена участка'})
        self.assertEqual(response.status_code, 403, response.text)
        other_site = next(s for s in self.rpc('master', 'references', 'sites') if s['id'] != self.site['id'])
        response = self.rpc_response('master', 'create_task', **self.task_body(site=other_site['name']))
        self.assertEqual(response.status_code, 400, response.text)

    def test_identical_retry_only_creates_one_task_and_changed_retry_is_rejected(self):
        request_id = uuid.uuid4().hex
        body = self.task_body()
        first = self.rpc_response('master', 'create_task', request_id=request_id, **body)
        self.assertEqual(first.status_code, 200, first.text)
        tid = first.json()['result']
        retry = self.rpc_response('master', 'create_task', request_id=request_id, **body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()['result'], tid)
        altered = self.rpc_response('master', 'create_task', request_id=request_id, **{**body, 'title': 'Другой наряд'})
        self.assertEqual(altered.status_code, 400, altered.text)
        cross_user = self.rpc_response('admin', 'create_task', request_id=request_id, **body)
        self.assertEqual(cross_user.status_code, 403, cross_user.text)
        tasks = [t for t in self.snapshot('master')['tasks'] if t['title'] == body['title']]
        self.assertEqual([t['id'] for t in tasks], [tid])

    def test_rejected_write_does_not_consume_retry_id(self):
        request_id = uuid.uuid4().hex
        body = self.task_body()
        bad = self.rpc_response('master', 'create_task', request_id=request_id, **{**body, 'title': 'x'})
        self.assertEqual(bad.status_code, 400, bad.text)
        corrected = self.rpc_response('master', 'create_task', request_id=request_id, **body)
        self.assertEqual(corrected.status_code, 200, corrected.text)

    def test_unplanned_photo_required_and_bad_photo_leaves_no_report_or_file(self):
        tid = self.issue()
        self.start('worker1', tid)
        body = dict(work='Контакты очищены, проверка выполнена.', result='Работает', defect='D-03', hours=1, materials=[])
        missing = self.rpc_response('worker1', 'submit', tid, **body)
        self.assertEqual(missing.status_code, 400, missing.text)
        corrupted = self.rpc_response('worker1', 'submit', tid, photos=[{
            'name': 'bad.jpg', 'content': base64.b64encode(b'broken photo').decode()}], **body)
        self.assertEqual(corrupted.status_code, 400, corrupted.text)
        self.assertEqual(self.rpc('worker1', 'task', tid)['status'], 'inProgress')
        self.assertFalse(any(r['task_id'] == tid for r in self.snapshot('worker1')['reports']))
        self.assertEqual(list(self.app.state.store.photos.iterdir()), [])

    def test_original_bytes_and_foreign_duplicate_evidence_stay_private(self):
        photo = self.photo()
        first_tid = self.issue('worker1')
        self.start('worker1', first_tid)
        first_rid = self.submit('worker1', first_tid, photos=[photo])
        second_tid = self.issue('worker2')
        self.start('worker2', second_tid)
        second_rid = self.submit('worker2', second_tid, photos=[photo])
        master = self.snapshot('master')
        first = next(r for r in master['reports'] if r['id'] == first_rid)
        second = next(r for r in master['reports'] if r['id'] == second_rid)
        duplicate = next(c for c in second['checks'] if c['id'] == 'photo_reused')
        self.assertEqual(duplicate['evidence']['source_report_id'], first_rid)
        worker = self.snapshot('worker2')
        visible = next(r for r in worker['reports'] if r['id'] == second_rid)
        self.assertNotIn('evidence', json.dumps(visible['checks']))
        self.assertNotIn(first_rid, [r['id'] for r in worker['reports']])
        self.assertNotIn(first_tid, [t['id'] for t in worker['tasks']])
        own = self.client.get('/api/photos/' + first['photos'][0], headers=self.headers('worker1'))
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.content, base64.b64decode(photo['content']))
        self.assertEqual(own.headers['cache-control'], 'no-store')
        foreign = self.client.get('/api/photos/' + first['photos'][0], headers=self.headers('worker2'))
        self.assertEqual(foreign.status_code, 403, foreign.text)
        anonymous = self.client.get('/api/photos/' + first['photos'][0])
        self.assertEqual(anonymous.status_code, 401, anonymous.text)
        history = self.rpc('worker2', 'equipment_history', self.equipment['name'])
        self.assertNotIn(first_tid, [t['id'] for t in history['tasks']])

    def test_foreign_task_read_transition_and_report_submission_are_denied(self):
        tid = self.issue('worker2')
        self.start('worker2', tid)
        for method, args, kwargs in [
            ('task', (tid,), {}), ('transition', (tid, 'paused'), {'reason': 'Чужая пауза'}),
            ('events', (tid,), {}), ('pauses', (tid,), {}),
            ('submit', (tid,), {'work': 'Выполнены необходимые работы', 'result': 'Проверено', 'defect': 'D-03', 'hours': 1, 'materials': []}),
        ]:
            with self.subTest(method=method):
                response = self.rpc_response('worker1', method, *args, **kwargs)
                self.assertEqual(response.status_code, 403, response.text)

    def test_private_snapshot_requires_session_and_logout_invalidates_token(self):
        self.assertEqual(self.client.get('/api/snapshot').status_code, 401)
        self.assertEqual(self.client.get('/api/snapshot', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        snapshot = self.snapshot('worker1')
        self.assertIn('references', snapshot)
        self.assertIn('alerts', snapshot)
        self.assertEqual(snapshot['attention'], {})
        self.assertEqual(snapshot['timezone'], 'Asia/Qyzylorda')
        self.assertNotIn('salt', json.dumps(snapshot))
        self.assertNotIn('password_hash', json.dumps(snapshot))
        logout = self.client.post('/api/logout', headers=self.headers('worker1'))
        self.assertEqual(logout.status_code, 200, logout.text)
        self.assertEqual(self.client.get('/api/snapshot', headers=self.headers('worker1')).status_code, 401)

    def test_api_rejects_actor_override_and_non_submit_photo_upload(self):
        forged = self.rpc_response('worker1', 'create_task', **{**self.task_body(), 'actor': self.sessions['master']['user']})
        self.assertEqual(forged.status_code, 400, forged.text)
        bad = self.rpc_response('master', 'references', photos=[self.photo()])
        self.assertEqual(bad.status_code, 400, bad.text)

    def test_mobile_shell_is_public_but_traversal_cannot_read_server_or_data(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200, home.text)
        self.assertIn("script-src 'self'", home.headers.get('content-security-policy', ''))
        self.assertEqual(home.headers.get('x-content-type-options'), 'nosniff')
        alternate = self.client.get('/web/index.html')
        self.assertEqual(alternate.status_code, 200, alternate.text)
        self.assertIn("script-src 'self'", alternate.headers.get('content-security-policy', ''))
        self.assertEqual(alternate.headers.get('x-content-type-options'), 'nosniff')
        for url in ['/web/app.js', '/web/styles.css', '/web/manifest.webmanifest', '/sw.js']:
            reply = self.client.get(url)
            self.assertEqual(reply.status_code, 200, url + ': ' + reply.text)
        for url in ['/web/%2e%2e/server/api.py', '/assets/%2e%2e/server/api.py', '/web/%2e%2e/server_config.json',
                    '/web/%2e%2e/server_data/naryadai.db', '/assets/%2e%2e/server_data/photos/example.jpg']:
            reply = self.client.get(url)
            self.assertIn(reply.status_code, (403, 404), url + ': ' + reply.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
