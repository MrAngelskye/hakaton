"""Transfer a backed-up SQLite database into an EMPTY PostgreSQL schema.

Run with the application server stopped. Never merge unrelated live databases.
Photos are uploaded before committing; uncommitted uploads are removed on error.
"""
import argparse,json,os,sqlite3,sys,hashlib,shutil
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.migrations import migrate,backfill,DB

ORDER=('sites','brigades','equipment','defect_codes','materials','users','work_norms','material_norms','tasks','reports','events','shift_rules','shifts','pauses','report_materials','task_photos','equipment_downtimes','task_assignments','brigade_memberships','task_refusals','ai_jobs','notification_outbox')
TRIGGERS=(('resolve_task_catalogs_trigger','tasks'),('resolve_report_defect_trigger','reports'),('sync_report_details_trigger','reports'),('task_audit_v2','tasks'),('downtime_guard_v2','equipment_downtimes'))

def transfer(source,database_env,backup_dir,upload_photos=False):
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.conninfo import conninfo_to_dict
    source=source.resolve(strict=True);backup_dir=backup_dir.resolve()
    if backup_dir.exists():raise ValueError('Backup directory must be new.')
    url=os.environ.get(database_env,'');info=conninfo_to_dict(url)
    if not url:raise ValueError('Set '+database_env+' in the environment.')
    if info.get('host') not in ('localhost','127.0.0.1','::1') and info.get('sslmode') not in ('require','verify-ca','verify-full'):raise ValueError('Remote PostgreSQL requires TLS.')
    backup_dir.mkdir(parents=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(backup_dir/'naryadai.db')) as backup:
        old.backup(backup)
    photo_dir=source.parent/'photos'
    if photo_dir.exists():shutil.copytree(photo_dir,backup_dir/'photos')
    hashes={str(p.relative_to(backup_dir)):hashlib.sha256(p.read_bytes()).hexdigest() for p in backup_dir.rglob('*') if p.is_file()}
    (backup_dir/'checksums.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    storage=None;uploaded=[]
    try:
        with closing(sqlite3.connect(backup_dir/'naryadai.db')) as old,psycopg.connect(url,row_factory=dict_row,prepare_threshold=None) as raw:
            old.row_factory=sqlite3.Row
            existing=raw.execute("SELECT to_regclass('naryadai.users') AS table_name").fetchone()['table_name']
            if existing:
                raw.execute('SET LOCAL search_path TO naryadai,public')
                if raw.execute('SELECT count(*) AS n FROM users').fetchone()['n']:raise ValueError('Target contains users. Choose an EMPTY dedicated PostgreSQL database.')
            else:
                raw.execute((Path(__file__).resolve().parents[1]/'server/sql/baseline001.sql').read_text(encoding='utf-8'))
            raw.execute('SET search_path TO naryadai,public');raw.execute("SET LOCAL TIME ZONE 'Asia/Qyzylorda'")
            raw.execute('SELECT pg_advisory_xact_lock(77410312)')
            migrate(raw,True)
            for name,table in TRIGGERS:raw.execute(f'DROP TRIGGER IF EXISTS {name} ON {table}')
            source_tables={r['name'] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            photo_keys=set()
            if 'reports' in source_tables:
                for r in old.execute('SELECT photos FROM reports'):photo_keys.update(json.loads(r['photos']))
            if 'task_photos' in source_tables:photo_keys.update(r['object_key'] for r in old.execute('SELECT object_key FROM task_photos'))
            if upload_photos:
                from server.storage import SupabaseStorage
                storage=SupabaseStorage(os.environ.get('SUPABASE_URL',''),os.environ.get('SUPABASE_SECRET_KEY',''),os.environ.get('STORAGE_BUCKET','naryadai-reports'));storage.ensure_bucket()
                for key in sorted(photo_keys):
                    if Path(key).name!=key:raise ValueError('Unsafe photo key.')
                    p=backup_dir/'photos'/key
                    if not p.is_file():raise ValueError('A referenced source photo is missing: '+key)
                    try:previous=storage.download(key)
                    except FileNotFoundError:storage.upload(key,p.read_bytes());uploaded.append(key)
                    else:
                        if hashlib.sha256(previous).digest()!=hashlib.sha256(p.read_bytes()).digest():raise ValueError('A target photo has different content: '+key)
            counts={};repeat_links=[]
            for table in ORDER:
                if table not in source_tables:continue
                target_columns={r['column_name'] for r in raw.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s',('naryadai',table))}
                columns=[r['name'] for r in old.execute('PRAGMA table_info('+table+')') if r['name'] in target_columns]
                quoted=','.join('"'+x.replace('"','""')+'"' for x in columns);rows=old.execute('SELECT '+quoted+' FROM '+table).fetchall()
                for row in rows:
                    values=[row[x] for x in columns]
                    if table=='tasks' and 'repeat_of_task_id' in columns and row['repeat_of_task_id'] is not None:
                        repeat_links.append((row['id'],row['repeat_of_task_id']));values[columns.index('repeat_of_task_id')]=None
                    if table=='task_photos' and 'is_demo' in columns:values[columns.index('is_demo')]=bool(values[columns.index('is_demo')])
                    raw.execute('INSERT INTO '+table+'('+quoted+') VALUES('+','.join('%s' for _ in columns)+')',tuple(values))
                counts[table]=len(rows)
            for task_id,previous_id in repeat_links:raw.execute('UPDATE tasks SET repeat_of_task_id=%s WHERE id=%s',(previous_id,task_id))
            backfill(DB(raw,True))
            # Restore trigger functions already installed by migration 002.
            for name,table in TRIGGERS:
                function={'resolve_task_catalogs_trigger':'resolve_task_catalogs','resolve_report_defect_trigger':'resolve_report_defect','sync_report_details_trigger':'sync_report_details','task_audit_v2':'audit_task_change','downtime_guard_v2':'guard_downtime'}[name]
                timing='AFTER' if name in ('sync_report_details_trigger','task_audit_v2') else 'BEFORE'
                operation='UPDATE' if name=='task_audit_v2' else 'INSERT OR UPDATE OF materials,photos' if name=='sync_report_details_trigger' else 'INSERT OR UPDATE'
                raw.execute(f'CREATE TRIGGER {name} {timing} {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()')
            for row in raw.execute("SELECT tablename FROM pg_tables WHERE schemaname='naryadai'").fetchall():
                table=row['tablename'];raw.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
                sequence=raw.execute('SELECT pg_get_serial_sequence(%s,%s) AS sequence',('naryadai.'+table,'id')).fetchone()['sequence'] if 'id' in DB(raw,True).columns(table) else None
                if sequence:raw.execute("SELECT setval(%s,GREATEST((SELECT COALESCE(MAX(id),1) FROM "+table+"),1),true)",(sequence,))
            raw.execute('REVOKE ALL ON ALL TABLES IN SCHEMA naryadai FROM PUBLIC');raw.execute('REVOKE ALL ON ALL SEQUENCES IN SCHEMA naryadai FROM PUBLIC')
            raw.commit()
        print(json.dumps({'imported':counts,'backup':str(backup_dir),'photos_uploaded':len(uploaded),'photos_referenced':len(photo_keys),'photo_files_migrated':upload_photos},ensure_ascii=False))
        if photo_keys and not upload_photos:print('Photo metadata transferred; files remain in the backup. Upload them to the private bucket before testing photo views.')
    except Exception:
        if storage:
            for key in uploaded:
                try:storage.delete(key)
                except OSError:pass
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--database-env',default='DATABASE_URL');parser.add_argument('--backup-dir',type=Path,required=True);parser.add_argument('--upload-photos',action='store_true')
    args=parser.parse_args()
    try:transfer(args.source,args.database_env,args.backup_dir,args.upload_photos)
    except Exception as error:print('Transfer stopped:',type(error).__name__,str(error),file=sys.stderr);sys.exit(1)
