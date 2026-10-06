"""PostgreSQL-адаптер для сохранения проверенных правил Store.
Все пользовательские значения передаются параметрами. Схема изолирована от Data API.
"""
import re,sqlite3,json,threading
from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from server.store import ServerStore

TABLES_WITH_IDS={'users','tasks','reports','events','pauses','sites','equipment','materials','defect_codes','brigades','work_norms','task_photos','task_assignments','brigade_memberships','equipment_downtimes','notification_outbox','task_refusals'}

class Row(dict):
    """Keep the cloud-1.4 wire format while PostgreSQL stores native types."""
    def __init__(self,values,json_columns=()):
        normalized={}
        for key,value in values.items():
            if key in json_columns:
                value=json.dumps(value,ensure_ascii=False)
            elif isinstance(value,datetime):
                if value.tzinfo is not None:value=value.astimezone(ZoneInfo('Asia/Qyzylorda')).replace(tzinfo=None)
                value=value.isoformat(timespec='seconds')
            elif isinstance(value,date):value=value.isoformat()
            elif isinstance(value,Decimal):value=float(value)
            normalized[key]=value
        super().__init__(normalized)
    def __getitem__(self,key):return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

def postgres_sql(sql):
    """Преобразовать только известные внутренние SQLite-конструкции."""
    text=sql.strip().rstrip(';')
    if text.startswith(('PRAGMA','BEGIN IMMEDIATE')):return 'SELECT 1'
    ignored=text.upper().startswith('INSERT OR IGNORE')
    if ignored:text=re.sub(r'^INSERT OR IGNORE','INSERT',text,flags=re.I)+' ON CONFLICT DO NOTHING'
    # Не заменять вопросительные знаки внутри строковых/идентификаторных литералов.
    out=[];quote=None;i=0
    while i<len(text):
        ch=text[i]
        if quote:
            out.append(ch)
            if ch==quote:
                if i+1<len(text) and text[i+1]==quote:out.append(text[i+1]);i+=1
                else:quote=None
        elif ch in ('\"',"'"):quote=ch;out.append(ch)
        elif text[i:i+3]=='end' and (i==0 or not (text[i-1].isalnum() or text[i-1]=='_')) and (i+3==len(text) or not (text[i+3].isalnum() or text[i+3]=='_')):
            out.append('"end"');i+=2
        else:out.append('%s' if ch=='?' else ch)
        i+=1
    return ''.join(out)

def postgres_ddl(sql):
    sql=re.sub(r'\bINTEGER PRIMARY KEY(?: AUTOINCREMENT)?\b','BIGSERIAL PRIMARY KEY',sql)
    return re.sub(r'\bREAL\b','DOUBLE PRECISION',sql)

class Cursor:
    def __init__(self,cursor,lastrowid=None):self.cursor=cursor;self.lastrowid=lastrowid
    def _row(self,row):
        json_columns={column.name for column in self.cursor.description if column.type_code in (114,3802)}
        return Row(row,json_columns)
    def fetchone(self):
        row=self.cursor.fetchone();return self._row(row) if row is not None else None
    def fetchall(self):return [self._row(row) for row in self.cursor.fetchall()]
    def __iter__(self):return iter(self.fetchall())

class Connection:
    def __init__(self,connection):self.connection=connection;self.write_locked=False
    def execute(self,sql,args=()):
        if not self.write_locked and re.match(r'\s*(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|BEGIN IMMEDIATE)',sql,re.I):
            # Serialize short mutations (including schedule validation) across server processes.
            # Read transactions never acquire this exclusive lock.
            self.connection.execute('SELECT pg_advisory_xact_lock(77410312)')
            self.connection.execute("SELECT set_config('naryadai.service_write','1',true)")
            self.write_locked=True
        sql=postgres_sql(sql);match=re.match(r'INSERT INTO\s+(\w+)',sql,re.I)
        returning=bool(match and match[1] in TABLES_WITH_IDS and 'RETURNING' not in sql.upper())
        if returning:sql+=' RETURNING id'
        try:cur=self.connection.execute(sql,args or None)
        except psycopg.IntegrityError:raise sqlite3.IntegrityError('Нарушение ограничений базы.') from None
        row=cur.fetchone() if returning else None
        last=row['id'] if row else None
        return Cursor(cur,last)
    def executemany(self,sql,rows):
        for row in rows:self.execute(sql,row)
    def executescript(self,script):
        for sql in script.split(';'):
            if sql.strip():self.execute(postgres_ddl(sql))

class PostgresStore(ServerStore):
    def __init__(self,directory,settings,storage):
        self.settings=settings;self.seed_password=settings.bootstrap_password;self.storage=storage
        self._local=threading.local()
        self.pool=ConnectionPool(settings.database_url,min_size=0,max_size=settings.database_pool_size,timeout=15,
           kwargs={'row_factory':dict_row,'connect_timeout':10,'prepare_threshold':None},open=True)
        with self._connect() as conn:
            conn.execute('CREATE SCHEMA IF NOT EXISTS naryadai')
            conn.execute('REVOKE ALL ON SCHEMA naryadai FROM PUBLIC')
        super().__init__(directory,settings)
        with self.transaction() as c:
            for table in TABLES_WITH_IDS:
                c.execute(f"SELECT setval('naryadai.{table}_id_seq',GREATEST((SELECT last_value FROM naryadai.{table}_id_seq),(SELECT COALESCE(MAX(id),1) FROM {table})),true)")
            for row in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='naryadai'"):
                table=row['tablename']
                if not re.fullmatch(r'[a-z_]+',table):raise ValueError('Недопустимое имя таблицы.')
                c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
    def _connect(self):
        try:return psycopg.connect(self.settings.database_url,row_factory=dict_row,connect_timeout=10,prepare_threshold=None)
        except psycopg.Error:raise sqlite3.OperationalError('PostgreSQL недоступен. Проверьте настройки соединения.') from None
    @contextmanager
    def transaction(self,write=False):
        current=getattr(self._local,'connection',None)
        if current is not None:
            yield current;return
        try:
            with self.pool.connection() as conn:
                conn.execute('SET LOCAL search_path TO naryadai,public')
                conn.execute("SET LOCAL TIME ZONE 'Asia/Qyzylorda'")
                wrapped=Connection(conn)
                if write:wrapped.execute('BEGIN IMMEDIATE')
                self._local.connection=wrapped;self._local.after_commit=[]
                try:
                    yield wrapped
                    conn.commit()
                    for fn in self._local.after_commit:fn()
                except Exception:conn.rollback();raise
                finally:self._local.connection=None;self._local.after_commit=[]
        except psycopg.OperationalError:raise sqlite3.OperationalError('PostgreSQL временно недоступен.') from None
    def close(self):self.pool.close()
    def save_photo(self,p):
        import uuid
        target=self.photos/(uuid.uuid4().hex+p.suffix.lower());self.storage.upload(target.name,p.read_bytes());return target
    def remove_photo(self,p):self.storage.delete(p.name)
    def read_photo(self,name):
        if name.startswith('demo_'):
            from server.demo_import import read_demo_photo
            return read_demo_photo(name)
        return self.storage.download(name)
