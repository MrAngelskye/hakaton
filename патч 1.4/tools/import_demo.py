"""Load the checked-in synthetic SQLite dataset into a NEW directory only."""
import argparse,hashlib,json,sqlite3,tempfile,zipfile
from contextlib import closing
from pathlib import Path

ARCHIVE=Path(__file__).resolve().parents[2]/'database'/'naryadai_database.zip'
SHA256='d36b1afb2c11f9a8c2f3a9da3827558d6fcb07da9a86d4435091ad0f96761a8e'
MARKER='.naryadai-demo-package.json'

def import_demo(directory,archive=ARCHIVE):
    target=Path(directory).resolve();marker=target/MARKER
    if target.exists():
        if not target.is_dir():raise ValueError('Путь занят файлом.')
        if marker.is_file() and (target/'naryadai.db').is_file():
            info=json.loads(marker.read_text(encoding='utf-8'))
            if info.get('archive_sha256')==SHA256:return info
        if any(target.iterdir()):raise ValueError('Импорт разрешён только в новую пустую папку. Существующая БД не изменяется.')
    archive=Path(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise ValueError('Контрольная сумма учебного архива не совпадает.')
    target.parent.mkdir(parents=True,exist_ok=True)
    # The validated archive is not extracted wholesale; only DB and flat JPEG names.
    with tempfile.TemporaryDirectory(prefix='.naryadai-import-',dir=target.parent) as temporary:
        staged=Path(temporary)/'data';staged.mkdir();(staged/'photos').mkdir()
        with zipfile.ZipFile(archive) as z:
            prefix='naryadai_database/generated/'
            (staged/'naryadai.db').write_bytes(z.read(prefix+'naryadai.db'))
            for entry in z.infolist():
                if not entry.filename.startswith(prefix+'photos/') or entry.is_dir():continue
                name=entry.filename[len(prefix+'photos/'):]
                if '/' in name or '\\' in name or Path(name).suffix.lower()!='.jpg':raise ValueError('Неверное имя учебной фотографии.')
                (staged/'photos'/name).write_bytes(z.read(entry))
        with closing(sqlite3.connect(staged/'naryadai.db')) as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Учебная SQLite повреждена.')
            counts={table:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('tasks','reports','users','equipment')}
        info={'archive_sha256':SHA256,'synthetic':True,'counts':counts}
        (staged/MARKER).write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        # Rename each verified file into an empty target; never replace an existing DB.
        if target.exists() and any(target.iterdir()):raise ValueError('Папка изменилась во время импорта. Выберите новую папку.')
        if target.exists():
            # Only an empty, explicitly resolved directory is removed.
            target.rmdir()
        staged.rename(target)
    return info

def main():
    p=argparse.ArgumentParser(description='Импорт 608 учебных нарядов в новую отдельную SQLite')
    p.add_argument('--data-dir',type=Path,required=True);args=p.parse_args()
    try:info=import_demo(args.data_dir)
    except (ValueError,OSError,zipfile.BadZipFile) as e:p.error(str(e))
    print(json.dumps(info,ensure_ascii=False,indent=2))
    print('Учебные логины master, master2, worker1–worker15, admin; пароль DemoOnly-2026!')
    print('При запуске приложения автоматически применяется миграция 002.')

if __name__=='__main__':main()
