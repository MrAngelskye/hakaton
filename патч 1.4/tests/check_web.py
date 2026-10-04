"""Resource and privacy contracts for the new public shell; no network or data mutations."""
import json
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'


class WebContract(unittest.TestCase):
    def test_manifest_installation_resources(self):
        manifest = json.loads((WEB / 'manifest.webmanifest').read_text(encoding='utf-8'))
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['scope'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        for icon in manifest['icons']:
            file = ROOT / icon['src'].lstrip('/')
            self.assertTrue(file.is_file(), file)
            if file.suffix == '.png':
                raw = file.read_bytes()
                self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', raw[16:24])
                self.assertEqual(icon['sizes'], f'{width}x{height}')

    def test_service_worker_only_public_shell(self):
        source = (WEB / 'sw.js').read_text(encoding='utf-8')
        shell = re.search(r'const SHELL = (\[.*?\]);', source).group(1)
        urls = json.loads(shell.replace("'", '"'))
        self.assertFalse(any(url.startswith('/api/') for url in urls))
        self.assertIn("url.pathname.startsWith('/api/')", source)
        self.assertIn('!SHELL.includes(url.pathname)', source)
        self.assertIn("event.request.method !== 'GET'", source)

    def test_auth_and_idempotent_report_transport(self):
        source = (WEB / 'app.js').read_text(encoding='utf-8')
        self.assertIn("sessionStorage.setItem('naryadai.token'", source)
        self.assertNotIn("localStorage.setItem('naryadai.token'", source)
        self.assertIn('pending.request_id', source)
        self.assertIn('pendingRequests:new Map()', source)
        self.assertIn('state.pendingRequests.get(key)||uuid()', source)
        self.assertIn('state.pendingRequests.clear()', source)
        self.assertIn('error.status>=400&&error.status<500', source)
        self.assertIn("cache:'no-store'", source)
        self.assertIn('URL.revokeObjectURL', source)
        self.assertIn('await clearDrafts()', source)
        self.assertIn('sessionToken!==state.token', source)

    def test_page_assets_and_reduced_motion(self):
        page = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertIn('lang="ru"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn('aria-labelledby="dialog-title"', page)
        for src in re.findall(r'(?:href|src)="(/web/[^"]+)"', page):
            self.assertTrue((ROOT / src.lstrip('/')).is_file(), src)
        css = (WEB / 'styles.css').read_text(encoding='utf-8')
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn('min-height:48px', css)


if __name__ == '__main__':
    unittest.main()
