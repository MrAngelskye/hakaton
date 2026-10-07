"""User settings isolation, frozen startup, and version compatibility."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import packaged
from tools import client_launcher
from worker_entry import load_worker, import_settings


class PackagedTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'user')})
        self.env.start()
        self.program = patch.object(packaged, 'program_dir', return_value=self.root / 'program')
        self.program.start()
        (self.root / 'program').mkdir()

    def tearDown(self):
        self.program.stop()
        self.env.stop()
        self.folder.cleanup()

    def test_settings_survive_program_replacement(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('NARYADAI_SERVER_URL', None)
            self.assertEqual(packaged.client_server(), packaged.DEFAULT_SERVER)
            old = self.root / 'program/client_config.json'
            old.write_text('{"server":"https://old.example.com"}')
            self.assertEqual(packaged.client_server(), 'https://old.example.com')
            packaged.save_object('client_config.json', {'server': 'https://new.example.com'})
            old.unlink()
            self.assertEqual(packaged.client_server(), 'https://new.example.com')

    def test_server_17_is_accepted(self):
        response = contextlib.closing(io.BytesIO(b'{"ok":true,"version":"1.7"}'))
        with patch.object(client_launcher, 'urlopen', return_value=response):
            client_launcher.wait_for_server('https://example.com', seconds=0)

    def test_malformed_settings_are_not_silently_replaced(self):
        path = packaged.save_object('client_config.json', {'server': 'https://example.com'})
        path.write_text('[]')
        with self.assertRaises(ValueError):
            packaged.client_server()
        self.assertEqual(path.read_text(), '[]')

    def test_worker_uses_explicit_settings_without_database_connection(self):
        worker = self.root / 'worker_config.json'
        server = self.root / 'server_config.json'
        worker.write_text(json.dumps({'server': 'https://example.com', 'token': 'x' * 32}))
        server.write_text(json.dumps({'api_key': 'local-secret', 'workspace': 'naryadai'}))
        with patch.dict(os.environ, {'DATABASE_URL': 'intentionally-invalid'}):
            instance = load_worker(worker, server)
        self.assertEqual(instance.ai.settings.api_key, 'local-secret')
        packaged.save_object('ai_paths.json', {'worker': str(worker), 'server': str(server)})
        self.assertEqual(packaged.worker_config_paths(), (worker, server))
        self.assertNotIn('local-secret', (packaged.configuration_dir() / 'ai_paths.json').read_text())

    def test_invalid_worker_token_is_rejected_before_saving_paths(self):
        worker = self.root / 'worker_config.json'
        server = self.root / 'server_config.json'
        worker.write_text(json.dumps({'server': 'https://example.com', 'token': 'short'}))
        server.write_text(json.dumps({'api_key': 'local-secret'}))
        with self.assertRaises(ValueError):
            load_worker(worker, server)
        self.assertFalse((packaged.configuration_dir() / 'ai_paths.json').exists())

    def test_imported_ai_settings_work_after_old_project_is_deleted(self):
        worker = self.root / 'worker_config.json'
        server = self.root / 'server_config.json'
        worker.write_text(json.dumps({'server': 'https://example.com', 'token': 'x' * 32}))
        server.write_text(json.dumps({'api_key': 'local-secret', 'database_url': 'private-database-password',
                                      'supabase_secret_key': 'private-storage-key'}))
        import_settings(worker, server)
        worker.unlink()
        server.unlink()
        paths = packaged.worker_config_paths()
        self.assertEqual(load_worker(*paths).ai.settings.api_key, 'local-secret')
        copied = paths[1].read_text()
        self.assertNotIn('private-database-password', copied)
        self.assertNotIn('private-storage-key', copied)


if __name__ == '__main__':
    unittest.main()
