"""Download the official small Russian Vosk model into Android assets.

Model files are build inputs, deliberately excluded from Git.
"""
from pathlib import Path, PurePosixPath
import hashlib
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'android/app/src/main/assets/model-ru'
CACHE = ROOT / '.dart_tool/vosk-model-small-ru-0.22.zip'
URL = 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'

def prepare():
    if (DEST / 'am/final.mdl').exists() and (DEST / 'uuid').exists():
        print('Russian voice model already prepared')
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        print('Downloading official Russian voice model', flush=True)
        with urllib.request.urlopen(URL, timeout=120) as source, CACHE.open('wb') as target:
            shutil.copyfileobj(source, target)
    digest = hashlib.sha256(CACHE.read_bytes()).hexdigest()
    if digest != '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4':
        raise ValueError('Russian voice model checksum mismatch')
    with zipfile.ZipFile(CACHE) as archive:
        for entry in archive.infolist():
            parts = PurePosixPath(entry.filename).parts
            if '..' in parts or not parts or parts[0] != 'vosk-model-small-ru-0.22':
                raise ValueError('Unexpected model archive entry')
            if entry.is_dir() or len(parts) == 1:
                continue
            target = DEST.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    (DEST / 'uuid').write_text(digest, encoding='utf-8')
    print('Russian voice model ready; SHA256:', digest)

if __name__ == '__main__':
    prepare()
