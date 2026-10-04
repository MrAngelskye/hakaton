"""Приватный Supabase Storage. Ключ существует только на сервере приложения."""
import json,mimetypes
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote

class SupabaseStorage:
    def __init__(self,url,key,bucket):
        self.url=url.rstrip('/')+'/storage/v1';self.key=key;self.bucket=bucket
    def request(self,path,data=None,method='GET',content_type='application/json'):
        headers={'apikey':self.key,'Content-Type':content_type}
        if self.key.startswith('eyJ'):headers['Authorization']='Bearer '+self.key
        request=Request(self.url+path,data=data,headers=headers,method=method)
        try:
            with urlopen(request,timeout=30) as r:
                body=r.read(8*1024*1024+1)
                if len(body)>8*1024*1024:raise OSError('Фото превышает ограничение 8 МБ.')
                return body
        except HTTPError as e:raise OSError(f'Supabase Storage: HTTP {e.code}. Проверьте ключ, бакет и лимиты.') from None
        except (URLError,TimeoutError):raise OSError('Нет связи с хранилищем фотографий.') from None
    def ensure_bucket(self):
        # POST повторно не нужен: проверяем существование и приватность бакета.
        try:raw=self.request('/bucket/'+quote(self.bucket,safe=''))
        except OSError as e:
            if 'HTTP 404' not in str(e) and 'HTTP 400' not in str(e):raise
            raw=self.request('/bucket',json.dumps({'id':self.bucket,'name':self.bucket,'public':False,'file_size_limit':8*1024*1024,'allowed_mime_types':['image/jpeg','image/png','image/webp']}).encode(),'POST')
            return
        bucket=json.loads(raw)
        if bucket.get('public'):raise ValueError('Бакет фотографий должен быть приватным.')
    def object_path(self,name):return '/object/'+quote(self.bucket,safe='')+'/'+quote(name,safe='')
    def upload(self,name,data):self.request(self.object_path(name),data,'POST',mimetypes.guess_type(name)[0] or 'application/octet-stream')
    def download(self,name):return self.request('/object/authenticated/'+quote(self.bucket,safe='')+'/'+quote(name,safe=''))
    def delete(self,name):self.request('/object/'+quote(self.bucket,safe=''),json.dumps({'prefixes':[name]}).encode(),'DELETE')
