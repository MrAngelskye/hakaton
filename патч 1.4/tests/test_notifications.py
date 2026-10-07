"""Notifications across authenticated API, durable store and desktop lifecycle."""
import os
import base64
from io import BytesIO
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.notification_content import notification_content
from server.api import create_app
from server.config import Settings


class NotificationAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(seed_demo=True,data_dir=Path(self.temp.name), ai_enabled=False))
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.headers = {}
        self.users = {}
        for login, role in [('master', 'master'), ('worker1', 'worker'), ('worker2', 'worker'), ('admin', 'admin')]:
            response = self.client.post('/api/login', json={'username': login, 'password': '1234', 'role': role})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.headers[login] = {'Authorization': 'Bearer ' + data['token']}
            self.users[login] = data['user']
        self.day = '2030-06-10'
        self.catalog = self.store.catalogs(self.users['master'])
        self.equipment = self.catalog['equipment'][0]

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.temp.cleanup()

    def call(self, who, method, args=(), kwargs=None, request_id=None, expected=200):
        response = self.client.post('/api/call/' + method, headers=self.headers[who], json={
            'args': list(args), 'kwargs': kwargs or {}, 'photos': [], 'request_id': request_id or uuid.uuid4().hex})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json().get('result')

    def create(self, **overrides):
        fields = dict(title='Проверка приводного агрегата', description='Проверить подшипники и контрольный запуск.',
                      site='', equipment='', site_id=self.equipment['site_id'], equipment_id=self.equipment['id'],
                      priority='normal', kind='Плановая', duration=1, day=self.day, start=9,
                      deadline=self.day + 'T18:00', worker_id=self.users['worker1']['id'])
        fields.update(overrides)
        return self.call('master', 'create_task', kwargs=fields)

    def inbox(self, who='worker1', kind=None):
        response = self.client.get('/api/notifications', headers=self.headers[who])
        self.assertEqual(response.status_code, 200)
        return [i for i in response.json()['items'] if kind is None or i['kind'] == kind]

    def test_urgent_assignment_priority_change_and_reassignment(self):
        tid = self.create(priority='urgent')
        alert = self.inbox()[0]
        self.assertEqual(alert['severity'], 'critical')
        self.assertEqual(alert['title'], 'Срочный наряд')
        self.assertIn(str(tid), alert['body'])
        self.assertEqual(self.inbox('worker2'), [])
        self.call('master', 'reassign_task', [tid, self.users['worker2']['id'], self.day, 10, 'Изменилась смена'])
        self.assertEqual(self.inbox('worker2')[0]['severity'], 'critical')
        ordinary = self.create(start=11)
        self.call('master', 'change_priority', [ordinary, 'urgent', 'Обнаружен аварийный дефект'])
        self.call('master', 'change_priority', [ordinary, 'urgent', 'Подтверждён аварийный дефект'])
        self.assertEqual(len(self.inbox(kind='urgent')), 1)

    def test_announcements_permissions_receipts_and_atomic_ack(self):
        fields = dict(title='Сбор бригады', message='В 15:00 у мастерской.', user_ids=[self.users['worker1']['id']], important=True)
        self.call('worker1', 'send_announcement', kwargs=fields, expected=403)
        self.call('master', 'send_announcement', kwargs={**fields, 'user_ids': [999999]}, expected=400)
        request_id = uuid.uuid4().hex
        self.assertEqual(self.call('master', 'send_announcement', kwargs=fields, request_id=request_id), {'recipients': 1})
        self.call('master', 'send_announcement', kwargs=fields, request_id=request_id)
        alert = self.inbox()[0]
        self.assertIsNone(alert['task_id'])
        self.assertEqual(len(self.inbox()), 1)
        self.assertEqual(self.inbox('worker2'), [])
        self.assertIn('мастер', alert['body'].lower())
        self.call('worker2', 'acknowledge_notification', [alert['id']], expected=403)
        self.call('worker1', 'acknowledge_notifications', [[alert['id'], 999999]], expected=403)
        self.assertEqual(len(self.inbox()), 1, 'Whole batch rolls back on foreign/missing ID')
        self.call('worker1', 'acknowledge_notifications', [[alert['id']]])
        self.assertEqual(self.inbox(), [])
        self.call('admin', 'send_announcement', kwargs={'title': 'Общая информация', 'message': 'Проверьте график смены.'})
        self.assertEqual(len(self.inbox()), 1)
        self.assertEqual(len(self.inbox('worker2')), 1)
        self.assertEqual(self.client.get('/api/notifications').status_code, 401)

    def test_deadline_boundary_dedup_and_finished_jobs(self):
        tid = self.create(deadline=self.day + 'T10:00')
        for _ in range(2):
            self.store.notification_tick(at=self.day + 'T09:31')
        self.assertEqual(len(self.inbox(kind='deadline_reminder')), 1)
        for _ in range(2):
            self.store.notification_tick(at=self.day + 'T10:00')
        self.assertEqual(len(self.inbox(kind='overdue')), 1)
        self.call('master', 'transition', [tid, 'cancelled', 'Работа отменена'])
        self.store.notification_tick(at=self.day + 'T10:31')
        self.assertEqual(len(self.inbox(kind='overdue')), 1)

    def test_next_job_waits_for_current_and_respects_shifts(self):
        current = self.create()
        next_id = self.create(start=10)
        self.call('worker1', 'transition', [current, 'inProgress'])
        self.store.notification_tick(at=self.day + 'T09:55')
        self.assertEqual(self.inbox(kind='next_task'), [])
        self.call('worker1', 'transition', [current, 'paused', 'Ожидаем запасную часть'])
        self.store.notification_tick(at=self.day + 'T10:00')
        self.assertEqual(self.inbox(kind='next_task'), [])
        self.call('master', 'transition', [current, 'cancelled', 'Передано другой бригаде'])
        for _ in range(2):
            self.store.notification_tick(at=self.day + 'T10:00')
        alerts = self.inbox(kind='next_task')
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['task_id'], next_id)
        self.create(start=16, deadline=self.day + 'T20:00')
        self.store.notification_tick(at=self.day + 'T18:01')
        self.assertEqual(len(self.inbox(kind='next_task')), 1)

    def test_night_shift_and_no_early_next_job(self):
        wid = self.users['worker1']['id']
        self.call('master', 'set_shift', [wid, self.day, 20, 32])
        tid = self.create(start=25, deadline='2030-06-11T08:00')
        self.store.notification_tick(at='2030-06-11T00:40')
        self.assertEqual(self.inbox(kind='next_task'), [])
        self.store.notification_tick(at='2030-06-11T00:55')
        self.assertEqual(self.inbox(kind='next_task')[0]['task_id'], tid)

    def test_browser_png_report_and_corrupt_photo(self):
        from PIL import Image
        tid=self.create(kind='Внеплановая')
        self.call('worker1','transition',[tid,'inProgress'])
        stream=BytesIO();Image.new('RGB',(120,80),'blue').save(stream,'PNG')
        kwargs={'work':'Подшипник заменён и крепления проверены.','result':'Контрольный запуск успешен.','defect':self.catalog['defect_codes'][1]['code'],'hours':1,'materials':[]}
        def report(photo):
            return self.client.post('/api/call/submit',headers=self.headers['worker1'],json={'args':[tid],'kwargs':kwargs,'photos':[photo],'request_id':uuid.uuid4().hex})
        bad=report({'name':'broken.png','content':base64.b64encode(b'not a photograph').decode()})
        self.assertEqual(bad.status_code,400)
        good=report({'name':'after.png','content':base64.b64encode(stream.getvalue()).decode()})
        self.assertEqual(good.status_code,200,good.text)
        saved=self.store.reports(self.users['master'],task_ids=[tid])[0]
        self.assertEqual(len(saved['photos']),1)
        photo=self.client.get('/api/photos/'+saved['photos'][0],headers=self.headers['worker1'])
        self.assertEqual(photo.content,stream.getvalue(),'Browser PNG bytes must remain intact')


class DesktopDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def test_persistent_dedup_logout_and_account_isolation(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QWidget
        from app.desktop_notifications import DesktopNotifications
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder)/'notifications.ini'), QSettings.Format.IniFormat)
            window = QWidget()
            store = type('Store', (), {'url': 'https://test.invalid'})()
            user = {'id': 1, 'name': 'Тестовый сотрудник'}
            items = [{'id': 7, 'kind': 'issued', 'task_id': 8, 'payload': {'title': 'Проверить насос', 'priority': 'urgent'}}]
            controller = DesktopNotifications(window, store, user, settings)
            with patch.object(controller, 'show') as display:
                controller.feed(items);controller.show_next();controller.feed(items);controller.show_next()
                self.assertEqual(display.call_count, 1)
                self.assertEqual(display.call_args.args[0], 'Срочный наряд')
                controller.feed([{**items[0], 'id': 9}]);controller.shutdown();controller.show_next()
                self.assertEqual(display.call_count, 1, 'Logging out cancels pending popup')
            another = DesktopNotifications(window, store, user, settings)
            with patch.object(another, 'show') as display:
                another.feed(items);another.show_next();self.assertFalse(display.called)
            another.shutdown()
            other_user = DesktopNotifications(window, store, {**user, 'id': 2}, settings)
            with patch.object(other_user, 'show') as display:
                other_user.feed(items);other_user.show_next();self.assertEqual(display.call_count, 1)
            other_user.shutdown();window.deleteLater()

    def test_backlog_is_grouped_and_read_alert_removed(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QWidget
        from app.desktop_notifications import DesktopNotifications
        with tempfile.TemporaryDirectory() as folder:
            window = QWidget();settings = QSettings(str(Path(folder)/'settings.ini'), QSettings.Format.IniFormat)
            controller = DesktopNotifications(window, object(), {'id': 4, 'name': 'Сотрудник'}, settings)
            items = [{'id': i, 'task_id': i, 'kind': 'issued', 'payload': {'title': 'Работа', 'priority': 'urgent' if i == 1 else 'normal'}} for i in range(1, 20)]
            with patch.object(controller, 'show') as display:
                controller.feed(items)
                self.assertEqual(len(controller.pending), 2)
                controller.show_next();controller.show_next()
                self.assertEqual(display.call_count, 2)
                controller.feed([{'id': 21, 'kind': 'announcement', 'payload': {'title': 'Сообщение'}}])
                controller.feed([]);controller.show_next()
                self.assertEqual(display.call_count, 2)
            controller.shutdown();window.deleteLater()


if __name__ == '__main__':
    unittest.main()
