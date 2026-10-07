"""One-time lossless metadata removal, with an audit containing no EXIF values."""
import hashlib
import io
import json
from pathlib import Path
from PIL import Image
from jpeg_metadata import jpeg_scan_sha256, optional_metadata, protected_segments_sha256, strip_optional_metadata

ROOT = Path(__file__).resolve().parent


def rgb_sha256(blob):
    with Image.open(io.BytesIO(blob)) as image:
        return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def main():
    audit_path = ROOT / 'metadata_sanitization.json'
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding='utf-8'))
        for entry in audit['files']:
            blob = (ROOT / entry['file_path']).read_bytes()
            if hashlib.sha256(blob).hexdigest() != entry['sha256_after'] or optional_metadata(blob):
                raise ValueError('Previously sanitized file changed; refusing to overwrite audit')
        print(json.dumps({'status':'already_sanitized_verified','files':len(audit['files'])}))
        return
    document = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    paths = [(asset, ROOT / asset['file_path']) for asset in document['assets']]
    paths.append((None, ROOT / 'contact_sheet.jpg'))
    records, prepared = [], []
    for asset, path in paths:
        original = path.read_bytes()
        old_hash = hashlib.sha256(original).hexdigest()
        if asset and old_hash != asset['sha256']:
            raise ValueError('Source image differs from manifest; refusing sanitization')
        removed = optional_metadata(original)
        cleaned = strip_optional_metadata(original)
        new_hash = hashlib.sha256(cleaned).hexdigest()
        rgb_before, rgb_after = rgb_sha256(original), rgb_sha256(cleaned)
        scan_before, scan_after = jpeg_scan_sha256(original), jpeg_scan_sha256(cleaned)
        protected_before = protected_segments_sha256(original)
        protected_after = protected_segments_sha256(cleaned)
        if rgb_before != rgb_after or scan_before != scan_after or protected_before != protected_after:
            raise ValueError('Lossless equality check failed; refusing any writes')
        record = {
            'file_path':path.relative_to(ROOT).as_posix(),
            'metadata_removed':bool(removed),'removed_segments':removed,
            'source_download_sha256':old_hash,
            'sha256_before':old_hash,'sha256_after':new_hash,
            'bytes_before':len(original),'bytes_after':len(cleaned),
            'decoded_rgb_sha256_before':rgb_before,'decoded_rgb_sha256_after':rgb_after,
            'jpeg_scan_sha256_before':scan_before,'jpeg_scan_sha256_after':scan_after,
            'protected_segments_sha256_before':protected_before,
            'protected_segments_sha256_after':protected_after,
            'pixels_reencoded':False,
        }
        records.append(record)
        prepared.append((asset, path, cleaned, record))
    # All checks pass before any file is modified.
    for asset, path, cleaned, record in prepared:
        if record['metadata_removed']:
            path.write_bytes(cleaned)
            if asset:
                kinds = ', '.join(v['segment'] for v in record['removed_segments'])
                asset.update(source_download_sha256=record['sha256_before'],
                             source_download_bytes=record['bytes_before'],
                             sha256=record['sha256_after'],downloaded_bytes=record['bytes_after'],
                             metadata_removed_segments=[v['segment'] for v in record['removed_segments']])
                asset['changes'] += (' Optional embedded JPEG metadata removed losslessly (' + kinds +
                    '); compressed scan, decoded RGB pixels and JFIF/ICC/Adobe segments unchanged. '
                    'Author and license attribution retained in manifest.json and ATTRIBUTIONS.md.')
    (ROOT / 'manifest.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    audit = {'checked_on':'2026-10-07','method':'Lossless JPEG segment removal: APP1, APP13 and COM; no pixel re-encoding',
             'protected_segments':'APP0/JFIF, APP2/ICC, APP14/Adobe preserved byte for byte',
             'contains_personal_metadata_values':False,'files':records,
             'changed_files':sum(r['metadata_removed'] for r in records),
             'all_rgb_hashes_equal':True,'all_scan_hashes_equal':True,'all_protected_segments_equal':True}
    audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# Attribution for public maintenance photographs','','Each image retains the individually listed source license. No company affiliation or repair certification is implied.','']
    for asset in document['assets']:
        lines.extend(['## '+asset['asset_id'],'','File: '+asset['file_path'],'','Credit: '+asset['attribution'],'',
                      'Source: ['+asset['source_title']+']('+asset['source_page_url']+')','',
                      'License: ['+asset['license']+']('+asset['license_url']+')','','Changes: '+asset['changes'],''])
    (ROOT / 'ATTRIBUTIONS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'files_checked':len(records),'metadata_removed_from':audit['changed_files'],
                      'rgb_and_scan_hashes_unchanged':True,'contact_sheet_reencoded':False}))


if __name__ == '__main__':
    main()
