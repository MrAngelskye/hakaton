"""Локальный HTTP-контракт Supabase Storage: приватность, ключи, откат фото."""
import json,sys,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.storage import SupabaseStorage

class StorageChecks(unittest.TestCase):
 def setUp(self):
  self.bucket=None;self.files={};self.headers=[];owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def response(self,data=b'{}',code=200):
    self.send_response(code);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   def read(self):return self.rfile.read(int(self.headers.get('Content-Length','0')))
   def do_GET(self):
    owner.headers.append(dict(self.headers))
    if self.path=='/storage/v1/bucket/naryadai-reports':self.response(json.dumps(owner.bucket).encode(),200 if owner.bucket else 404)
    elif self.path.startswith('/storage/v1/object/authenticated/naryadai-reports/'):
     self.response(owner.files[self.path.rsplit('/',1)[-1]])
    else:self.response(code=404)
   def do_POST(self):
    owner.headers.append(dict(self.headers));data=self.read()
    if self.path=='/storage/v1/bucket':owner.bucket=json.loads(data)
    elif self.path.startswith('/storage/v1/object/naryadai-reports/'):owner.files[self.path.rsplit('/',1)[-1]]=data
    else:self.response(code=404);return
    self.response()
   def do_DELETE(self):
    owner.headers.append(dict(self.headers))
    for name in json.loads(self.read())['prefixes']:owner.files.pop(name,None)
    self.response()
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.storage=SupabaseStorage('http://127.0.0.1:'+str(self.server.server_port),'sb_secret_test-only','naryadai-reports')
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_private_upload_download_delete_and_secret_header(self):
  self.storage.ensure_bucket();self.assertFalse(self.bucket['public']);self.assertEqual(self.bucket['file_size_limit'],8*1024*1024)
  self.storage.upload('test.png',b'photo-bytes');self.assertEqual(self.storage.download('test.png'),b'photo-bytes')
  self.storage.delete('test.png');self.assertFalse(self.files)
  for h in self.headers:self.assertEqual(h['Apikey'],'sb_secret_test-only');self.assertNotIn('Authorization',h)
 def test_public_bucket_rejected_and_legacy_bearer(self):
  self.bucket={'public':True}
  with self.assertRaises(ValueError):self.storage.ensure_bucket()
  self.bucket={'public':False};self.storage.key='eyJtest-legacy-key';self.storage.ensure_bucket()
  self.assertEqual(self.headers[-1]['Authorization'],'Bearer eyJtest-legacy-key')

if __name__=='__main__':unittest.main(verbosity=2)
