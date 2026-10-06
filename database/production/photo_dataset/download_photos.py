"""Download the manifest's allowlisted public photos and pin their local hashes.

No credentials, login, uploads or image synthesis. Uses Pillow only to verify bytes.
"""
import argparse
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from PIL import Image
from jpeg_metadata import optional_metadata, strip_optional_metadata

ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = {'upload.wikimedia.org', 'thumb.wikimedia.org'}
HEADERS = {'User-Agent': 'NaryadAI-OpenPhotoDataset/1.0 (source-attributed public research)'}
MAX_BYTES = 10 * 1024 * 1024

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, default=ROOT / 'manifest.json')
    args = parser.parse_args()
    document = json.loads(args.manifest.read_text(encoding='utf-8'))
    failures = []
    for asset in document['assets']:
        target = ROOT / asset['file_path']
        target.resolve().relative_to(ROOT.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        url = asset['download_url']
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username:
            raise ValueError(f'Unapproved public download host: {url}')
        if target.exists() and asset.get('sha256'):
            blob = target.read_bytes()
            if hashlib.sha256(blob).hexdigest() == asset['sha256']:
                if optional_metadata(blob):
                    raise ValueError('Existing image contains optional metadata; sanitize the dataset first')
                print(json.dumps({'asset':asset['asset_id'],'status':'already_verified'}), flush=True)
                continue
            raise ValueError(f'Hash mismatch in existing file: {target.name}')
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as response:
                if urllib.parse.urlsplit(response.geturl()).hostname not in ALLOWED_HOSTS:
                    raise ValueError('Unexpected redirect host')
                blob = response.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                raise ValueError('Image exceeds 10 MiB download limit')
            with Image.open(io.BytesIO(blob)) as check:
                if check.format != 'JPEG':
                    raise ValueError(f'Expected JPEG, received {check.format}')
                dimensions = list(check.size)
                check.verify()
            source_sha256 = hashlib.sha256(blob).hexdigest()
            if asset['download_url'] == asset['original_image_url'] and hashlib.sha1(blob).hexdigest() != asset['original_sha1']:
                raise ValueError('Original-file SHA-1 differs from the Commons record')
            expected_source = asset.get('source_download_sha256') or asset.get('sha256')
            if expected_source and source_sha256 != expected_source:
                raise ValueError('Downloaded image no longer matches its pinned source-download SHA-256')
            cleaned = strip_optional_metadata(blob)
            sha256 = hashlib.sha256(cleaned).hexdigest()
            if asset.get('sha256') and sha256 != asset['sha256']:
                raise ValueError('Sanitized image does not match its pinned final SHA-256')
            target.write_bytes(cleaned)
            asset.pop('download_error', None)
            asset.update(download_status='downloaded_verified', source_download_sha256=source_sha256, sha256=sha256, image_dimensions=dimensions, downloaded_bytes=len(cleaned))
            print(json.dumps({'asset':asset['asset_id'],'status':asset['download_status'],'bytes':len(cleaned),'dimensions':dimensions}), flush=True)
        except Exception as error:
            asset.update(download_status='failed', download_error=str(error))
            failures.append(asset['asset_id'])
            print(json.dumps({'asset':asset['asset_id'],'status':'failed','error':str(error)}), flush=True)
        args.manifest.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        time.sleep(1)
    print(json.dumps({'verified':sum(a['download_status']=='downloaded_verified' for a in document['assets']),'failures':failures}))
    if failures:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
