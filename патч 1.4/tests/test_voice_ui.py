"""Native report dictation acceptance checks: no microphone, no speech service."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget, QTextEdit
from app.voice_input import ReportVoiceInput


class FakeSession:
    def __init__(self, path, **callbacks):
        self.callbacks = callbacks
        self.alive = False
        self.cancelled = False
        self.stopped = False

    def start(self):
        self.alive = True
        self.callbacks['on_status']('Микрофон включён')
        return True

    def is_alive(self):
        return self.alive

    def stop(self):
        self.stopped = True

    def cancel(self):
        self.cancelled = True
        self.alive = False
        self.callbacks['on_done']()

    def finish(self, text):
        self.alive = False
        self.callbacks['on_final'](text)
        self.callbacks['on_done']()


class VoiceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = QWidget()
        self.work, self.result = QTextEdit(self.parent), QTextEdit(self.parent)
        self.voice = ReportVoiceInput([('Работы', self.work), ('Проверка', self.result)], self.parent, FakeSession)
        self.voice.model_path = lambda: Path(self.temp.name)
        self.changes = []
        self.work.textChanged.connect(lambda: self.changes.append(self.work.toPlainText()))

    def tearDown(self):
        self.voice.dispose()
        self.parent.close()
        self.temp.cleanup()

    def test_review_append_and_existing_draft_event(self):
        self.work.setPlainText('Существующая запись')
        self.voice.open(self.work, 'Работы')
        self.voice.start()
        self.voice.session.callbacks['on_partial']('Предварительно')
        self.assertEqual(self.work.toPlainText(), 'Существующая запись')
        self.assertTrue(self.voice.has_unapplied())
        self.voice.stop()
        self.assertTrue(self.voice.session.stopped)
        self.voice.session.finish('Проверены крепления')
        self.assertEqual(self.work.toPlainText(), 'Существующая запись')
        self.voice.preview.setPlainText('Исправленное название узла')
        self.work.setPlainText('Ручная правка')
        self.voice.apply()
        self.assertEqual(self.work.toPlainText(), 'Ручная правка\nИсправленное название узла')
        self.assertEqual(self.changes[-1], self.work.toPlainText())
        self.assertFalse(self.voice.has_unapplied())
        self.voice.open(self.result, 'Проверка')
        self.voice.start()
        self.voice.session.finish('Контрольная проверка выполнена')
        self.voice.apply()
        self.assertEqual(self.result.toPlainText(), 'Контрольная проверка выполнена')

    def test_cancel_dispose_and_late_callbacks(self):
        self.voice.open(self.work, 'Работы')
        self.voice.start()
        previous = self.voice.session
        self.voice.cancel()
        previous.finish('Поздний текст после отмены')
        self.assertTrue(previous.cancelled)
        self.assertEqual(self.voice.preview.toPlainText(), '')
        self.assertEqual(self.work.toPlainText(), '')
        self.voice.open(self.work, 'Работы')
        self.voice.start()
        previous = self.voice.session
        self.voice.dispose()
        previous.finish('После закрытия формы')
        self.assertTrue(previous.cancelled)
        self.assertEqual(self.work.toPlainText(), '')

    def test_target_change_and_limit_do_not_discard_text(self):
        self.voice.open(self.work, 'Работы')
        self.voice.preview.setPlainText('Не добавленный текст')
        self.voice.open(self.result, 'Проверка')
        self.assertIs(self.voice.target, self.work)
        self.work.setPlainText('x' * 9999)
        self.voice.apply()
        self.assertEqual(len(self.work.toPlainText()), 9999)
        self.assertEqual(self.voice.preview.toPlainText(), 'Не добавленный текст')
        self.assertIn('ничего не добавлено', self.voice.status.text())

    def test_missing_model_keeps_manual_report_editable(self):
        self.voice.model_path = lambda: Path(self.temp.name) / 'not-installed'
        self.voice.open(self.work, 'Работы')
        self.voice.start()
        self.assertIsNone(self.voice.session)
        self.assertFalse(self.voice.busy)
        self.assertTrue(self.work.isEnabled())
        self.assertIn('install_voice.bat', self.voice.status.text())

    def test_actual_report_draft_restore_submission_and_voice_guard(self):
        from datetime import date, timedelta
        from app.store import Store
        from app.dialogs import SubmitReport
        store = Store(self.temp.name,seed_demo=True)
        master = store.authenticate('master', '1234', 'master')
        worker = store.authenticate('worker1', '1234', 'worker')
        equipment = store.catalogs(master)['equipment'][0]
        site = next(item for item in store.catalogs(master)['sites'] if item['id'] == equipment['site_id'])
        day = (date.today() + timedelta(days=180)).isoformat()
        task_id = store.create_task(master, title='Проверка голосового отчёта', description='Проверить узел и описать результат', site=site['name'], equipment=equipment['name'], equipment_id=equipment['id'], priority='normal', kind='Плановая', duration=1, day=day, start=8, deadline=day+'T18:00', worker_id=worker['id'])
        store.transition(worker, task_id, 'accepted')
        store.transition(worker, task_id, 'inProgress')
        report = SubmitReport(store, worker, store.task(worker, task_id), self.parent)
        report.voice.session_factory = FakeSession
        report.voice.model_path = lambda: Path(self.temp.name)
        for field, text in ((report.work, 'Проверены крепления и состояние узла.'), (report.result_text, 'Контрольная проверка выполнена, результат зафиксирован.')):
            report.voice.open(field, 'Отчёт')
            report.voice.start()
            report.voice.session.finish(text)
            report.voice.apply()
        saved = report.draft.load()
        self.assertEqual(saved['work'], report.work.toPlainText())
        self.assertEqual(saved['result'], report.result_text.toPlainText())
        report.voice.dispose()
        report.close()
        restored = SubmitReport(store, worker, store.task(worker, task_id), self.parent)
        self.assertEqual(restored.work.toPlainText(), saved['work'])
        restored.voice.open(restored.work, 'Работы')
        restored.voice.preview.setPlainText('Не проверенная диктовка')
        restored.save()
        self.assertEqual(store.task(worker, task_id)['status'], 'inProgress')
        self.assertIn('Добавьте распознанный текст', restored.error.text())
        restored.voice.cancel()
        restored.save()
        actual = store.latest_report(worker, task_id)
        self.assertEqual(actual['work'], saved['work'])
        self.assertEqual(actual['result'], saved['result'])
        self.assertFalse(restored.draft.load())
        restored.voice.dispose()
        restored.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
