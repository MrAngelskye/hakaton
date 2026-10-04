"""PostgreSQL-адаптер для сохранения проверенных правил Store.
Все пользовательские значения передаются параметрами. Схема изолирована от Data API.
"""
import re,sqlite3
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from server.store import ServerStore

TABLES_WITH_IDS={'users','tasks','reports','events','pauses','reference_items','task_alerts','work_sessions'}

class Row(dict):
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
    def fetchone(self):
        row=self.cursor.fetchone();return Row(row) if row is not None else None
    def fetchall(self):return [Row(row) for row in self.cursor.fetchall()]
    def __iter__(self):return iter(self.fetchall())

class Connection:
    def __init__(self,connection):self.connection=connection
    def execute(self,sql,args=()):
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
    @staticmethod
    def _columns(c,table):
        return {r['column_name'] for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='naryadai' AND table_name=?",(table,))}
    def __init__(self,directory,settings,storage):
        self.settings=settings;self.seed_password=settings.bootstrap_password;self.storage=storage
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
    def transaction(self):
        with self._connect() as conn:
            conn.execute('SET search_path TO naryadai,public')
            # Один короткий общий замок: атомарные назначения и очередь даже при перезапуске процесса.
            conn.execute('SELECT pg_advisory_xact_lock(77410312)')
            yield Connection(conn)
    def save_photo(self,p):
        import uuid
        target=self.photos/(uuid.uuid4().hex+p.suffix.lower());self.storage.upload(target.name,p.read_bytes());return target
    def remove_photo(self,p):self.storage.delete(p.name)
    def read_photo(self,name):return self.storage.download(name)
