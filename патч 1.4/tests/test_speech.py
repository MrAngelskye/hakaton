"""Offline dictation lifecycle and model installer checks; no real microphone.

These tests neither install optional packages nor download a model, and never
open the application's database. They do not measure real speech accuracy.
"""
import builtins
import io
import json
import stat
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.speech import DictationSession, MODEL_NAME, valid_model_path, native_model_path
from tools import setup_voice


class FakeRecognizer:
    def __init__(self, model, rate):
        self.rate = rate
        self.last = b''
        self.final_calls = 0

    def AcceptWaveform(self, data):
        self.last = data
        return data == b'complete'

    def Result(self):
        return json.dumps({'text': 'заменен подшипник'}, ensure_ascii=False)

    def PartialResult(self):
        return json.dumps({'partial': 'проверен'}, ensure_ascii=False)

    def FinalResult(self):
        self.final_calls += 1
        return json.dumps({'text': 'проверен контрольный запуск'}, ensure_ascii=False)


class FakeStream:
    def __init__(self, chunks, *, callback, **kwargs):
        self.chunks = chunks
        self.callback = callback
        self.kwargs = kwargs
        self.closed = False

    def __enter__(self):
        for data in self.chunks:
            self.callback(data, 1, None, None)
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed = True


class DictationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model = Path(self.temp.name) / MODEL_NAME
        for name in ('am/final.mdl', 'conf/mfcc.conf'):
            path = self.model / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fake model for lifecycle tests')
        self.events = []
        self.done = threading.Event()
        self.streams = []
        self.recognizers = []

    def tearDown(self):
        self.temp.cleanup()

    def make_session(self, chunks=None, **changes):
        def stream_factory(**kwargs):
            stream = FakeStream(chunks if chunks is not None else [b'complete', b'tail'], **kwargs)
            self.streams.append(stream)
            return stream

        def recognizer_factory(model, rate):
            recognizer = FakeRecognizer(model, rate)
            self.recognizers.append(recognizer)
            return recognizer

        options = dict(model_path=self.model,
            on_status=lambda text: self.events.append(('status', text)),
            on_partial=lambda text: self.events.append(('partial', text)),
            on_final=lambda text: self.events.append(('final', text)),
            on_error=lambda text: self.events.append(('error', text)),
            on_done=self.done.set,
            model_factory=lambda path: object(), recognizer_factory=recognizer_factory,
            stream_factory=stream_factory,
            device_info_factory=lambda: {'default_samplerate': 48000.0}, max_seconds=.03)
        options.update(changes)
        return DictationSession(**options)

    def wait(self, session):
        self.assertTrue(self.done.wait(2), 'dictation worker did not finish')
        session._thread.join(timeout=2)
        self.assertFalse(session.is_alive())

    def test_stop_keeps_final_tail_and_closes_microphone(self):
        def status(text):
            if text == 'Слушаю…':
                session.stop()
        session = self.make_session(on_status=status)
        self.assertTrue(session.start())
        self.wait(session)
        self.assertEqual([text for event, text in self.events if event == 'final'],
                         ['заменен подшипник проверен контрольный запуск'])
        self.assertFalse(any(event == 'error' for event, _ in self.events))
        self.assertTrue(self.streams[0].closed)
        self.assertEqual(self.streams[0].kwargs['samplerate'], 48000)
        self.assertEqual(self.streams[0].kwargs['dtype'], 'int16')
        self.assertEqual(self.streams[0].kwargs['channels'], 1)
        self.assertEqual(self.recognizers[0].rate, 48000)
        self.assertEqual(self.recognizers[0].final_calls, 1)

    def test_timeout_finishes_once_and_second_start_is_rejected(self):
        session = self.make_session()
        self.assertTrue(session.start())
        self.assertFalse(session.start())
        self.wait(session)
        self.assertFalse(session.start())
        self.assertEqual(sum(event == 'final' for event, _ in self.events), 1)
        self.assertTrue(self.streams[0].closed)

    def test_cancel_discards_output_and_releases_stream(self):
        def status(text):
            if text == 'Слушаю…':
                session.cancel()
        session = self.make_session(on_status=status)
        session.start()
        self.wait(session)
        self.assertEqual(self.events, [])
        self.assertTrue(self.streams[0].closed)
        self.assertEqual(self.recognizers[0].final_calls, 0)

    def test_stop_or_cancel_during_model_load_never_opens_microphone(self):
        for operation in ('stop', 'cancel'):
            with self.subTest(operation=operation):
                self.done.clear()
                self.events.clear()
                loaded = threading.Event()
                release = threading.Event()
                def model_factory(path):
                    loaded.set()
                    self.assertTrue(release.wait(2))
                    return object()
                session = self.make_session(model_factory=model_factory)
                session.start()
                self.assertTrue(loaded.wait(2))
                getattr(session, operation)()
                release.set()
                self.wait(session)
                self.assertEqual(self.streams, [])
                self.assertFalse(any(event in ('partial', 'final', 'error') for event, _ in self.events))

    def test_overflow_is_visible_and_never_returns_incomplete_transcript(self):
        session = self.make_session(chunks=[b'tail'] * 70)
        session.start()
        self.wait(session)
        errors = [text for event, text in self.events if event == 'error']
        self.assertEqual(len(errors), 1)
        self.assertIn('не успевает', errors[0])
        self.assertFalse(any(event == 'final' for event, _ in self.events))
        self.assertTrue(self.streams[0].closed)
        self.assertLessEqual(session._queue.qsize(), 64)

    def test_missing_model_leaves_microphone_closed(self):
        session = self.make_session(model_path=self.model / 'missing')
        session.start()
        self.wait(session)
        self.assertEqual(self.streams, [])
        self.assertIn('модель не найдена', self.events[0][1])

    def test_missing_optional_dependency_has_manual_input_guidance(self):
        original_import = builtins.__import__
        def missing_import(name, *args, **kwargs):
            if name == 'vosk':
                raise ImportError('not installed')
            return original_import(name, *args, **kwargs)
        session = self.make_session(model_factory=None, recognizer_factory=None)
        with patch('builtins.__import__', side_effect=missing_import):
            session.start()
            self.wait(session)
        self.assertIn('install_voice.bat', self.events[0][1])
        self.assertEqual(self.streams, [])

    def test_unavailable_device_has_clear_error(self):
        def unavailable():
            raise RuntimeError('device denied')
        session = self.make_session(device_info_factory=unavailable)
        session.start()
        self.wait(session)
        self.assertIn('Микрофон недоступен', [text for event, text in self.events if event == 'error'][0])
        self.assertEqual(self.streams, [])

    def test_failed_recognizer_closes_stream(self):
        class BrokenRecognizer(FakeRecognizer):
            def AcceptWaveform(self, data):
                raise RuntimeError('recognizer failed')
        session = self.make_session(recognizer_factory=BrokenRecognizer)
        session.start()
        self.wait(session)
        self.assertEqual(sum(event == 'error' for event, _ in self.events), 1)
        self.assertFalse(any(event == 'final' for event, _ in self.events))
        self.assertTrue(self.streams[0].closed)

    def test_callback_failure_cannot_leak_microphone(self):
        def broken_callback(text):
            raise RuntimeError('closed widget')
        session = self.make_session(on_partial=broken_callback)
        session.start()
        self.wait(session)
        self.assertTrue(self.streams[0].closed)
        self.assertEqual(sum(event == 'final' for event, _ in self.events), 1)

    def test_native_alias_is_only_passed_to_factory_original_path_is_retained(self):
        locations = []
        def model_factory(path):
            locations.append(path)
            return object()
        session = self.make_session(model_factory=model_factory)
        alias = 'C:\\NARYAD~1\\MODEL~1'
        with patch('app.speech.native_model_path', return_value=alias):
            session.start()
            self.wait(session)
        self.assertEqual(locations, [alias])
        self.assertEqual(session.model_path, self.model)


class NativePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model = Path(self.temp.name) / 'Русская модель'
        self.model.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_non_windows_keeps_unicode_path(self):
        with patch('app.speech.sys.platform', 'linux'), patch('app.speech._windows_short_path') as conversion:
            self.assertEqual(native_model_path(self.model), str(self.model.resolve()))
            conversion.assert_not_called()

    def test_windows_uses_verified_ascii_short_alias(self):
        alias = 'C:\\NARYAD~1\\MODEL~1'
        with patch('app.speech.sys.platform', 'win32'), \
                patch('app.speech._windows_short_path', return_value=alias) as conversion, \
                patch('app.speech.valid_model_path', return_value=True), \
                patch('app.speech.os.path.samefile', return_value=True):
            self.assertEqual(native_model_path(self.model), alias)
            conversion.assert_called_once_with(str(self.model.resolve()))

    def test_windows_missing_or_non_ascii_alias_has_clear_fallback(self):
        for alias in (None, str(self.model), 'C:\\папка\\MODEL~1'):
            with self.subTest(alias=alias), patch('app.speech.sys.platform', 'win32'), \
                    patch('app.speech._windows_short_path', return_value=alias):
                with self.assertRaisesRegex(RuntimeError, 'короткую папку с латинскими буквами'):
                    native_model_path(self.model)

    def test_windows_rejects_alias_to_different_or_incomplete_model(self):
        alias = 'C:\\NARYAD~1\\MODEL~1'
        for valid, same_file in ((False, True), (True, False)):
            with self.subTest(valid=valid, same_file=same_file), patch('app.speech.sys.platform', 'win32'), \
                    patch('app.speech._windows_short_path', return_value=alias), \
                    patch('app.speech.valid_model_path', return_value=valid), \
                    patch('app.speech.os.path.samefile', return_value=same_file):
                with self.assertRaisesRegex(RuntimeError, 'Vosk не может открыть'):
                    native_model_path(self.model)

    def test_windows_conversion_error_has_clear_fallback(self):
        with patch('app.speech.sys.platform', 'win32'), \
                patch('app.speech._windows_short_path', side_effect=OSError('8.3 unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Существующие файлы модели не изменены'):
                native_model_path(self.model)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_zip(self, target, extra=None):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr(MODEL_NAME + '/am/final.mdl', b'test')
            archive.writestr(MODEL_NAME + '/conf/mfcc.conf', b'test')
            for name, content in extra or []:
                item = zipfile.ZipInfo(name)
                item.filename = name
                item.orig_filename = name
                archive.writestr(item, content)

    def test_install_is_atomic_and_reuses_existing_model(self):
        target = self.root / 'models' / MODEL_NAME
        self.assertFalse(target.exists())
        def downloader(path):
            self.assertFalse(target.exists())
            self.write_zip(path)
        setup_voice.install_model(target, downloader=downloader)
        self.assertTrue(valid_model_path(target))
        self.assertEqual(list(target.parent.iterdir()), [target])
        def no_download(path):
            self.fail('a complete model should not be redownloaded')
        setup_voice.install_model(target, downloader=no_download)

    def test_incomplete_existing_folder_is_never_modified(self):
        target = self.root / MODEL_NAME
        target.mkdir()
        marker = target / 'personal.txt'
        marker.write_text('keep me')
        with self.assertRaisesRegex(RuntimeError, 'неполна'):
            setup_voice.install_model(target, downloader=lambda path: self.fail('unexpected download'))
        self.assertEqual(marker.read_text(), 'keep me')
        self.assertEqual(list(target.iterdir()), [marker])

    def test_zip_traversal_and_platform_absolute_paths_are_rejected_before_writing(self):
        for unsafe in (MODEL_NAME + '/../../escape.txt', '/escape.txt',
                       'C:/escape.txt', MODEL_NAME + '\\escape.txt', MODEL_NAME + '/file:stream',
                       MODEL_NAME + '/NUL.txt', MODEL_NAME + '/am/final.mdl.'):
            with self.subTest(unsafe=unsafe):
                archive = self.root / 'model.zip'
                self.write_zip(archive, [(unsafe, b'bad')])
                staging = self.root / 'extracted'
                with self.assertRaises(RuntimeError):
                    setup_voice.extract_model(archive, staging)
                self.assertFalse(staging.exists())
                self.assertFalse((self.root / 'escape.txt').exists())

    def test_zip_symlink_and_duplicate_case_alias_are_rejected(self):
        archive = self.root / 'model.zip'
        self.write_zip(archive)
        with zipfile.ZipFile(archive, 'a') as source:
            link = zipfile.ZipInfo(MODEL_NAME + '/link')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            source.writestr(link, '/outside')
        with self.assertRaisesRegex(RuntimeError, 'ссылку'):
            setup_voice.extract_model(archive, self.root / 'extracted')
        self.write_zip(archive, [(MODEL_NAME + '/AM/FINAL.MDL', b'overwrite')])
        with self.assertRaisesRegex(RuntimeError, 'повторяющийся'):
            setup_voice.extract_model(archive, self.root / 'extracted')

    def test_declared_expansion_limit_prevents_any_extraction(self):
        archive = self.root / 'model.zip'
        self.write_zip(archive)
        with patch.object(setup_voice, 'MAX_EXTRACTED', 1):
            with self.assertRaisesRegex(RuntimeError, 'размер'):
                setup_voice.extract_model(archive, self.root / 'extracted')
        self.assertFalse((self.root / 'extracted').exists())

    def test_readonly_check_does_not_create_target(self):
        target = self.root / 'not-created' / MODEL_NAME
        self.assertEqual(setup_voice.main(['--check', '--model-only', '--target', str(target)]), 2)
        self.assertFalse(target.parent.exists())

    def test_download_size_bound_and_redirect_guard(self):
        class Response(io.BytesIO):
            headers = {}
            url = setup_voice.MODEL_URL
            def geturl(self):
                return self.url
        response = Response(b'too big')
        destination = self.root / 'model.zip'
        with patch.object(setup_voice.urllib.request, 'urlopen', return_value=response), patch.object(setup_voice, 'MAX_DOWNLOAD', 2):
            with self.assertRaisesRegex(RuntimeError, 'предел'):
                setup_voice.download_model(destination)
        self.assertFalse(destination.exists())
        response = Response(b'ok')
        response.url = 'https://unexpected.example/model.zip'
        with patch.object(setup_voice.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'адрес'):
                setup_voice.download_model(destination)
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
