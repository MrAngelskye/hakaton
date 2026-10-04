"""Initialize a dedicated PostgreSQL test schema and load the synthetic fixture."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent


def postgres_connection(variable):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    url=os.environ.get(variable,'')
    if not url: raise ValueError('Set the environment variable '+variable+' locally before running.')
    info=conninfo_to_dict(url)
    if info.get('host') not in ('127.0.0.1','localhost','::1') and info.get('sslmode') not in ('require','verify-ca','verify-full'):
        raise ValueError('Remote database connections require sslmode=require or certificate verification.')
    return psycopg.connect(url,autocommit=True,connect_timeout=10,prepare_threshold=None)


class Storage:
    def __init__(self,bucket):
        url=os.environ.get('SUPABASE_URL','').rstrip('/')
        self.key=os.environ.get('SUPABASE_SECRET_KEY',''); self.bucket=bucket
        parsed=urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co'):
            raise ValueError('SUPABASE_URL must be your HTTPS Supabase project URL.')
        if not self.key: raise ValueError('Set SUPABASE_SECRET_KEY on this machine.')
        self.base=url+'/storage/v1'; self.uploaded=[]
    def request(self,path,data=None,method='GET',content_type='application/json'):
        headers={'apikey':self.key,'Content-Type':content_type}
        if self.key.startswith('eyJ'): headers['Authorization']='Bearer '+self.key
        req=Request(self.base+path,data=data,headers=headers,method=method)
        with urlopen(req,timeout=30) as response: return response.read(8*1024*1024+1)
    def ensure_bucket(self):
        try: value=json.loads(self.request('/bucket/'+quote(self.bucket,safe='')))
        except HTTPError as error:
            if error.code!=404: raise
            self.request('/bucket',json.dumps({'id':self.bucket,'name':self.bucket,'public':False,
                'file_size_limit':8*1024*1024,'allowed_mime_types':['image/jpeg','image/png','image/webp']}).encode(),'POST')
            return
        if value.get('public'): raise ValueError('The photo bucket must be private.')
    def upload(self,name,raw):
        suffix=quote(self.bucket,safe='')+'/'+quote(name,safe='')
        try:
            existing=self.request('/object/authenticated/'+suffix)
        except HTTPError as error:
            if error.code not in (400,404): raise
        else:
            if hashlib.sha256(existing).digest()!=hashlib.sha256(raw).digest():
                raise ValueError('Existing storage object has different content: '+name)
            return
        self.request('/object/'+suffix,raw,'POST','image/jpeg'); self.uploaded.append(name)
    def cleanup(self):
        for name in self.uploaded:
            try: self.request('/object/'+quote(self.bucket,safe=''),json.dumps({'prefixes':[name]}).encode(),'DELETE')
            except Exception: print('Storage cleanup pending for newly uploaded demo object:',name,file=sys.stderr)


def load(data_dir,variable,upload_photos,bucket):
    manifest=json.loads((data_dir/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('synthetic') is not True: raise ValueError('This loader accepts the generated demonstration package only.')
    schema=(ROOT/'schema.sql').read_text(encoding='utf-8')
    seed=(data_dir/'seed.sql').read_text(encoding='utf-8')
    storage=None; committed=False
    with postgres_connection(variable) as c:
        c.execute(schema,prepare=False)
        c.execute("SET search_path TO naryadai,public")
        users=c.execute('SELECT count(*) FROM users').fetchone()[0]
        existing=c.execute("SELECT value->>'dataset_id' FROM demo_metadata WHERE key='dataset'").fetchone()
        if users and (not existing or existing[0]!=manifest['dataset_id']):
            raise ValueError('Target database contains other data; choose a new dedicated test database.')
        try:
            if upload_photos:
                storage=Storage(bucket); storage.ensure_bucket()
                fixture=json.loads((data_dir/'demo.json').read_text(encoding='utf-8'))
                for index,photo in enumerate(fixture['task_photos'],1):
                    key=photo['object_key']
                    if Path(key).name!=key: raise ValueError('Unsafe storage key.')
                    raw=(data_dir/'photos'/key).read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=photo['sha256']: raise ValueError('Photo hash mismatch: '+key)
                    storage.upload(key,raw)
                    if index%100==0: print('Demo images checked/uploaded:',index)
            c.execute(seed,prepare=False); committed=True
            result=c.execute('SELECT count(*) FROM tasks').fetchone()[0]
            print('PostgreSQL import complete. Tasks:',result)
            print('Synthetic history:',manifest['history_from'],'through',manifest['history_until'])
            if not upload_photos:
                print('Photo metadata imported. Cloud photo files require --upload-photos or manual upload to the private bucket.')
        except Exception:
            # The seed runs in one transaction; release any failed transaction first.
            c.execute('ROLLBACK')
            if storage and not committed: storage.cleanup()
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-env',default='DATABASE_URL',help='Name of environment variable; never pass a password as an argument')
    parser.add_argument('--data-dir',type=Path,default=ROOT/'generated')
    parser.add_argument('--upload-photos',action='store_true',help='Upload labelled synthetic images to your private Supabase bucket')
    parser.add_argument('--bucket',default='naryadai-reports')
    args=parser.parse_args()
    try: load(args.data_dir.resolve(),args.database_env,args.upload_photos,args.bucket)
    except Exception as error:
        print('Import stopped:',type(error).__name__,str(error),file=sys.stderr); sys.exit(1)
