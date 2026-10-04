"""Client regressions: uncertain replies, safe drafts, cross-session refreshes.

No real HTTP server/model or user data. Photo files and draft paths are temporary.
"""
import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.drafts import ReportDraft, clear_user_drafts
from app.remote import RemoteStore


class DraftChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SimpleNamespace(path=Path(self.temp.name) / 'db', url='https://server-one.example')
        self.user = {'id': 2}

    def tearDown(self):
        self.temp.cleanup()

    def test_drafts_are_scoped_by_server_account_and_task(self):
        original = ReportDraft(self.store, self.user, 10)
        original.save({'work': 'Первый отчёт', 'hours': 1, 'materials': []})
        other_server = ReportDraft(SimpleNamespace(path=self.store.path, url='https://server-two.example'), self.user, 10)
        other_account = ReportDraft(self.store, {'id': 3}, 10)
        other_task = ReportDraft(self.store, self.user, 11)
        self.assertEqual(other_server.load(), {})
        self.assertEqual(other_account.load(), {})
        self.assertEqual(other_task.load(), {})
        self.assertEqual(original.load()['work'], 'Первый отчёт')

    def test_malformed_draft_fields_cannot_break_qt_restore(self):
        draft = ReportDraft(self.store, self.user, 10)
        draft.save({'work': ['unexpected'], 'result': {'unexpected': 1}, 'defect': 4, 'hours': float('nan'),
                    'materials': [None, {'name': 'Смазка', 'quantity': 2}],
                    'photo_sources': [None, 5, '/tmp/a.jpg', '/tmp/b.jpg', '/tmp/c.jpg', '/tmp/d.jpg']})
        restored = draft.load()
        self.assertNotIn('work', restored)
        self.assertNotIn('result', restored)
        self.assertNotIn('defect', restored)
        self.assertNotIn('hours', restored)
        self.assertEqual(restored['materials'], [{'name': 'Смазка', 'quantity': '2', 'unit': '', 'price': ''}])
        self.assertEqual(restored['photo_sources'], ['/tmp/a.jpg', '/tmp/b.jpg', '/tmp/c.jpg'])
        draft.path.write_text('{broken', encoding='utf-8')
        self.assertEqual(draft.load(), {})

    def test_failed_atomic_replace_preserves_old_draft_and_logout_cleans_pending(self):
        draft = ReportDraft(self.store, self.user, 10)
        draft.save({'work': 'Сохранённый текст', 'hours': 1, 'materials': []})
        with patch('app.drafts.os.replace', side_effect=OSError('temporary filesystem failure')):
            with self.assertRaises(OSError):
                draft.save({'work': 'Новый текст', 'hours': 2, 'materials': []})
        self.assertEqual(draft.load()['work'], 'Сохранённый текст')
        self.assertTrue(draft.path.with_suffix('.pending').is_file())
        other = ReportDraft(self.store, {'id': 3}, 10)
        other.save({'work': 'Чужой черновик', 'hours': 1, 'materials': []})
        clear_user_drafts(self.store, self.user)
        self.assertFalse(draft.path.exists())
        self.assertFalse(draft.path.with_suffix('.pending').exists())
        self.assertEqual(other.load()['work'], 'Чужой черновик')

    def test_cleanup_continues_after_one_inaccessible_file(self):
        first = ReportDraft(self.store, self.user, 10)
        second = ReportDraft(self.store, self.user, 11)
        first.save({'work': 'Первый', 'materials': []})
        second.save({'work': 'Второй', 'materials': []})
        original_unlink = Path.unlink
        def remove(path, *args, **kwargs):
            if path == first.path:
                raise PermissionError('locked draft')
            return original_unlink(path, *args, **kwargs)
        with patch('pathlib.Path.unlink', remove):
            with self.assertRaises(OSError):
                clear_user_drafts(self.store, self.user)
        self.assertTrue(first.path.exists())
        self.assertFalse(second.path.exists())


class RemoteRetryChecks(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.remote = RemoteStore('https://temporary.example', transport=lambda *args: {'ok': True, 'version': '1.4'})
        self.remote.token = 'temporary-token'
        self.remote.actor = {'id': 2, 'role': 'worker'}

    def tearDown(self):
        self.remote.transport = lambda *args: {'ok': True}
        self.remote.logout()
        self.remote._cache.cleanup()

    def test_lost_submission_reply_retries_same_id_and_exact_original_photo(self):
        accepted = {}
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / 'photo.jpg'
            image = Image.new('RGB', (48, 48), 'blue')
            exif = Image.Exif(); exif[36867] = '2026:10:04 10:00:00'
            image.save(photo, 'JPEG', exif=exif)
            original = photo.read_bytes()
            def transport(path, payload, token, binary):
                self.sent.append(json.loads(json.dumps(payload)))
                request_id = payload['request_id']
                if request_id not in accepted:
                    accepted[request_id] = 77
                    raise OSError('reply lost after server accepted report')
                return {'result': accepted[request_id]}
            self.remote.transport = transport
            kwargs = dict(work='Контакты очищены', result='Запуск выполнен', defect='D-03', hours=1, materials=[], photo_sources=[str(photo)])
            with self.assertRaises(OSError):
                self.remote.submit(self.remote.actor, 10, **kwargs)
            self.assertEqual(self.remote.submit(self.remote.actor, 10, **kwargs), 77)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(self.sent[0]['request_id'], self.sent[1]['request_id'])
            self.assertEqual(self.sent[0]['photos'], self.sent[1]['photos'])
            self.assertEqual(base64.b64decode(self.sent[1]['photos'][0]['content']), original)

    def test_http_503_keeps_request_id_for_retry(self):
        self.remote.transport = None
        count = 0
        def urlopen(request, timeout):
            nonlocal count
            payload = json.loads(request.data)
            self.sent.append(payload); count += 1
            if count == 1:
                raise HTTPError(request.full_url, 503, 'unavailable', None, io.BytesIO(b'{"detail":"temporary"}'))
            return io.BytesIO(b'{"result":23}')
        with patch('app.remote.urlopen', urlopen):
            with self.assertRaises(OSError):
                self.remote.call('transition', 10, 'accepted')
            self.assertEqual(self.remote.call('transition', 10, 'accepted'), 23)
        self.assertEqual(self.sent[0]['request_id'], self.sent[1]['request_id'])
        self.assertEqual(self.remote._retry_requests, {})

    def test_http_400_is_validation_and_does_not_pin_new_request_id(self):
        self.remote.transport = None
        count = 0
        def urlopen(request, timeout):
            nonlocal count
            self.sent.append(json.loads(request.data)); count += 1
            if count == 1:
                raise HTTPError(request.full_url, 400, 'bad input', None, io.BytesIO(b'{"detail":"invalid field"}'))
            return io.BytesIO(b'{"result":23}')
        with patch('app.remote.urlopen', urlopen):
            with self.assertRaises(ValueError):
                self.remote.call('transition', 10, 'accepted')
            self.assertEqual(self.remote.call('transition', 10, 'accepted'), 23)
        self.assertNotEqual(self.sent[0]['request_id'], self.sent[1]['request_id'])

    def test_logout_clears_retry_ids_snapshot_and_downloaded_photos(self):
        self.remote._retry_requests['fingerprint'] = 'request-id'
        self.remote._snapshot = {'private': 'old worker'}
        photo = self.remote.photos / 'private.jpg'; photo.write_bytes(b'private')
        self.remote.logout()
        self.assertEqual(self.remote.token, '')
        self.assertIsNone(self.remote.actor)
        self.assertIsNone(self.remote._snapshot)
        self.assertEqual(self.remote._retry_requests, {})
        self.assertFalse(photo.exists())

    def test_inaccessible_photo_does_not_preserve_session_or_stop_other_cleanup(self):
        first=self.remote.photos/'locked.jpg';second=self.remote.photos/'removed.jpg'
        first.write_bytes(b'private');second.write_bytes(b'private')
        original_unlink=Path.unlink
        def remove(path,*args,**kwargs):
            if path==first:raise PermissionError('locked photo')
            return original_unlink(path,*args,**kwargs)
        with patch('pathlib.Path.unlink',remove):
            with self.assertRaises(OSError):self.remote.logout()
        self.assertEqual(self.remote.token,'');self.assertIsNone(self.remote.actor)
        self.assertTrue(first.exists());self.assertFalse(second.exists())


class SnapshotSessionChecks(unittest.TestCase):
    def test_old_account_snapshot_cannot_override_new_account(self):
        from app.windows import MainWindow
        current = {'reports': ['new-account-only']}
        store = SimpleNamespace(actor={'id': 3}, token='new-token', _snapshot=current)
        window = SimpleNamespace(store=store, user={'id': 2})
        MainWindow.remote_snapshot(window, {'day': '2026-10-04', 'reports': ['old-account']})
        self.assertIs(store._snapshot, current)

    def test_old_session_snapshot_ignored_even_when_same_account_logs_in_again(self):
        from app.windows import MainWindow, SnapshotLoader
        current = {'reports': ['new-session-only']}
        store = SimpleNamespace(actor={'id': 2}, token='old-token', _snapshot=current)
        loader = SnapshotLoader(store, '2026-10-04', None)
        store.token = 'new-token'
        window = SimpleNamespace(store=store, user={'id': 2}, sender=lambda: loader)
        MainWindow.remote_snapshot(window, {'day': '2026-10-04', 'reports': ['old-session']})
        self.assertIs(store._snapshot, current)


if __name__ == '__main__':
    unittest.main(verbosity=2)
