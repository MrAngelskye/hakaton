"""Create a separate clean database; credentials are written outside the repo."""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
sys.path.insert(0,str(ROOT))

from app.production_data import bootstrap, import_photo_manifest, load_reference_package, make_credentials
from app.production_schema import BUSINESS_TABLES


def require_empty_sqlite(directory):
    database=directory/'naryadai.db'
    if not database.exists():return
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in BUSINESS_TABLES:
            if table in tables and c.execute('SELECT count(*) FROM '+table).fetchone()[0]:
                raise ValueError('Выберите отдельную пустую папку. Существующая БД не изменена.')


def require_empty_postgres(url):
    import psycopg
    with psycopg.connect(url,connect_timeout=10) as c:
        for table in BUSINESS_TABLES:
            if c.execute('SELECT to_regclass(%s)',('naryadai.'+table,)).fetchone()[0]:
                if c.execute('SELECT count(*) FROM naryadai.'+table).fetchone()[0]:
                    raise ValueError('Выберите отдельную пустую PostgreSQL. Существующая БД не изменена.')


def reserve_credentials(path, rows):
    path=path.expanduser().resolve()
    if path.is_relative_to(REPO.resolve()):
        raise ValueError('Файл паролей должен находиться за пределами репозитория.')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=('username','role','name','password'))
            writer.writeheader();writer.writerows(rows)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def main():
    parser=argparse.ArgumentParser(description='Подготовить отдельную рабочую БД без демонстрационных нарядов.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--sqlite-dir',type=Path,help='Отдельная пустая папка для локальной проверки')
    mode.add_argument('--postgres-config',type=Path,help='Приватный JSON с database_url отдельной PostgreSQL')
    parser.add_argument('--credentials',required=True,type=Path,help='Новый локальный CSV за пределами репозитория')
    parser.add_argument('--catalog',type=Path,default=REPO/'database'/'production'/'reference_catalog.json')
    parser.add_argument('--photo-manifest',type=Path,default=REPO/'database'/'production'/'photo_dataset'/'database_import.json')
    args=parser.parse_args()
    payload=load_reference_package(args.catalog)
    photos=json.loads(args.photo_manifest.read_text(encoding='utf-8'))
    photo_root=args.photo_manifest.resolve().parent
    for photo in photos.get('photos',photos.get('training_photos',[])):
        image=(photo_root/photo['relative_path']).resolve()
        if not image.is_relative_to(photo_root) or hashlib.sha256(image.read_bytes()).hexdigest()!=photo['sha256']:
            raise ValueError('Фотография отсутствует, путь недопустим или SHA-256 не совпадает.')
    if args.sqlite_dir:
        directory=args.sqlite_dir.expanduser().resolve();require_empty_sqlite(directory)
        from app.store import Store
        store=Store(directory,seed_demo=False)
    else:
        from server.config import Settings
        settings=Settings.load(args.postgres_config)
        if not settings.database_url:raise ValueError('В конфигурации отсутствует database_url.')
        if settings.seed_demo:raise ValueError('Для рабочей БД seed_demo должен быть false.')
        require_empty_postgres(settings.database_url)
        from server.postgres import PostgresStore
        store=PostgresStore(settings.data_dir,settings,storage=None)
    credentials_path=None
    committed=False
    try:
        rows=make_credentials(payload)
        credentials_path=reserve_credentials(args.credentials,rows)
        # Both catalogs and photos are atomic, including nested Store transactions.
        with store.transaction(write=True):
            result=bootstrap(store,payload,rows)
            result['training_reference_photos']=import_photo_manifest(store,photos)
        committed=True
        result['credentials_file']=str(credentials_path)
        result['notice']='Пароли существуют только в указанном локальном CSV. Не загружайте его в GitHub.'
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception:
        if credentials_path is not None and not committed:credentials_path.unlink(missing_ok=True)
        raise
    finally:store.close()


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:
        print('Подготовка не выполнена: '+str(error),file=sys.stderr)
        raise SystemExit(1)
