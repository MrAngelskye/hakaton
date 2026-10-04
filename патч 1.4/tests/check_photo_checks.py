"""Deterministic photos/EXIF and safe AI context, using generated images only."""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.photo_checks import fingerprint, inspect_report_fields, inspect_submission, visible_checks
from server.anythingllm import AnythingLLM

AT = datetime.fromisoformat('2026-10-04T12:00:00+05:00')
VERDICT = {'score': 78, 'verdict': 'acceptable', 'summary': 'Отчёт содержит выполненные действия.',
           'findings': [], 'criteria': {'description': 20, 'matching': 20, 'verification': 22, 'materials_time': 16}}


class PhotoChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.executescript('CREATE TABLE tasks(id INTEGER,created TEXT);'
                            'CREATE TABLE reports(id INTEGER,task_id INTEGER,photos TEXT,checks TEXT);'
                            "INSERT INTO tasks VALUES(1,'2026-10-04T08:00:00+05:00');")
        self.store = SimpleNamespace(photos=self.folder, read_photo=lambda name: (self.folder / name).read_bytes())

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def photo(self, name='source.jpg', captured=None, offset=None, quality=95):
        image = Image.new('RGB', (96, 96))
        image.putdata([(x * 2, y * 2, ((x // 12 + y // 12) % 2) * 220)
                       for y in range(96) for x in range(96)])
        exif = Image.Exif()
        if captured:
            exif[36867] = captured
        if offset:
            exif[36881] = offset
        path = self.folder / name
        image.save(path, quality=quality, exif=exif)
        return path

    def inspect(self, *paths):
        return inspect_submission(self.c, self.store, 1, paths, at=AT)

    def previous(self, path, *, report_id=10, task_id=2, indexed=False):
        checks = [{'id': 'photo_metadata', 'photo_index': 0, 'metadata': fingerprint(path.read_bytes())}] if indexed else []
        self.c.execute('INSERT INTO reports VALUES(?,?,?,?)', (report_id, task_id, json.dumps([path.name]), json.dumps(checks)))

    def test_no_exif_is_information_and_upload_time_is_separate(self):
        checks = self.inspect(self.photo())
        missing = next(c for c in checks if c['id'] == 'capture_time_missing')
        self.assertEqual(missing['severity'], 'info')
        metadata = next(c for c in checks if c['id'] == 'photo_metadata')['metadata']
        self.assertEqual(metadata['uploaded_at'], AT.isoformat())
        self.assertIsNone(metadata['captured_at'])
        self.assertFalse(any(c['severity'] == 'block' for c in checks))

    def test_exif_before_task_warns_but_does_not_block(self):
        checks = self.inspect(self.photo(captured='2026:10:03 10:00:00', offset='+05:00'))
        old = next(c for c in checks if c['id'] == 'capture_before_task')
        self.assertEqual(old['severity'], 'warn')
        self.assertFalse(any(c['severity'] == 'block' for c in checks))

    def test_exif_future_and_timezone_assumption(self):
        checks = self.inspect(self.photo(captured='2026:10:04 15:00:00'))
        self.assertIn('capture_in_future', [c['id'] for c in checks])
        metadata = next(c for c in checks if c['id'] == 'photo_metadata')['metadata']
        self.assertTrue(metadata['capture_timezone_assumed'])
        self.assertTrue(metadata['captured_at'].endswith('+05:00'))

    def test_configurable_age_and_no_filesystem_date_inference(self):
        self.c.execute("UPDATE tasks SET created='2026-10-01T08:00:00+05:00'")
        self.store.photo_check_policy = {'max_age_hours': 4}
        checks = self.inspect(self.photo(captured='2026:10:04 06:00:00'))
        self.assertIn('capture_too_old', [c['id'] for c in checks])
        self.store.photo_check_policy = {'max_age_hours': None}
        self.assertNotIn('capture_too_old', [c['id'] for c in self.inspect(self.folder / 'source.jpg')])

    def test_corrupt_photo_blocks_before_storage(self):
        path = self.folder / 'bad.jpg'
        path.write_bytes(b'not an image')
        checks = self.inspect(path)
        self.assertEqual(checks[0]['id'], 'invalid_image')
        self.assertEqual(checks[0]['severity'], 'block')

    def test_exact_reuse_warns_and_hides_foreign_report_identity(self):
        path = self.photo()
        self.previous(path)
        checks = self.inspect(path)
        reused = next(c for c in checks if c['id'] == 'photo_reused')
        self.assertEqual(reused['evidence']['source_report_id'], 10)
        self.assertEqual(reused['severity'], 'warn')
        self.assertNotIn('evidence', next(c for c in visible_checks(checks, 'worker') if c['id'] == 'photo_reused'))
        self.assertIn('evidence', next(c for c in visible_checks(checks, 'master') if c['id'] == 'photo_reused'))
        self.assertIn('evidence', reused)  # The original stored checks were not mutated.

    def test_recompressed_photo_detected_as_approximate(self):
        original = self.photo('old.jpg')
        self.previous(original, indexed=True)
        changed = self.folder / 'new.jpg'
        with Image.open(original) as image:
            image.save(changed, quality=75)
        self.assertNotEqual(fingerprint(original.read_bytes())['sha256'], fingerprint(changed.read_bytes())['sha256'])
        self.assertIn('photo_similar', [c['id'] for c in self.inspect(changed)])

    def test_indexed_cloud_history_does_not_download_photos(self):
        path = self.photo()
        self.previous(path, indexed=True)
        self.store.storage = object()
        self.store.read_photo = lambda name: self.fail('Indexed history should not download photos')
        self.assertIn('photo_reused', [c['id'] for c in self.inspect(path)])

    def test_unindexed_cloud_history_is_explicitly_partial(self):
        path = self.photo()
        self.previous(path)
        self.store.storage = object()
        self.store.read_photo = lambda name: self.fail('No network download inside submission')
        self.assertIn('legacy_history_partial', [c['id'] for c in self.inspect(path)])

    def test_revision_can_reuse_same_task_photo(self):
        path = self.photo()
        self.previous(path, task_id=1)
        self.assertNotIn('photo_reused', [c['id'] for c in self.inspect(path)])

    def test_flat_images_do_not_match_just_by_perceptual_hash(self):
        first = self.folder / 'blue.png'
        second = self.folder / 'green.png'
        Image.new('RGB', (96, 96), 'blue').save(first)
        Image.new('RGB', (96, 96), 'green').save(second)
        self.previous(first)
        self.assertNotIn('photo_similar', [c['id'] for c in self.inspect(second)])

    def test_field_validation_identifies_fields_without_requiring_materials(self):
        fields = inspect_report_fields(work='a', result='', hours=float('nan'), materials=[{'name': 'x'}])
        self.assertEqual({c['field'] for c in fields}, {'work', 'result', 'hours', 'materials'})
        self.assertEqual(inspect_report_fields(work='Контакты очищены', result='Проверено', hours=1, materials=[]), [])

    def test_ai_keeps_real_warning_without_private_evidence_and_uses_pillow(self):
        path = self.photo()
        self.previous(path)
        checks = self.inspect(path)
        settings = SimpleNamespace(send_images=True, workspace='reports')
        ai = AnythingLLM(settings)
        sent = []
        ai.request = lambda endpoint, payload: (sent.append(payload) or {'textResponse': json.dumps(VERDICT)})
        task = dict(title='Осмотр', description='Проверить узел', equipment='Конвейер', site='Участок', kind='Внеплановая', duration=1)
        report = dict(work='Контакты очищены', result='Запуск выполнен', defect='Нет', hours=1, materials=[], photos=[path.name], checks=checks)
        result = ai.review(task, report, self.folder)
        self.assertEqual(result['verdict'], 'needs_clarification')
        self.assertTrue(any(f.startswith('Фото 1:') for f in result['findings']))
        self.assertNotIn('source_report_id', sent[0]['message'])
        self.assertNotIn('sha256', sent[0]['message'])
        self.assertEqual(len(sent[0]['attachments']), 1)
        data = base64_decode(sent[0]['attachments'][0]['contentString'])
        with Image.open(io.BytesIO(data)) as image:
            self.assertLessEqual(max(image.size), 1280)
        self.assertFalse(any(key.startswith('PySide6') for key in sys.modules))


def base64_decode(data):
    import base64
    return base64.b64decode(data.split(',', 1)[1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
