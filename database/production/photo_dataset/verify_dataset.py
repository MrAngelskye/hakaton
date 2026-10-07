"""Offline integrity/provenance QA and database import adapter; no network."""
import collections
import hashlib
import json
from pathlib import Path
from PIL import Image
from jpeg_metadata import optional_metadata, jpeg_scan_sha256, protected_segments_sha256

ROOT = Path(__file__).resolve().parent

def main():
    document = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    audit = json.loads((ROOT / 'metadata_sanitization.json').read_text(encoding='utf-8'))
    audit_files = {entry['file_path']:entry for entry in audit['files']}
    hashes = set()
    sources, photos, errors = [], [], []
    for asset in document['assets']:
        path = ROOT / asset['file_path']
        try:
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != asset['sha256']:
                raise ValueError('SHA-256 mismatch')
            if optional_metadata(blob):
                raise ValueError('Optional EXIF/XMP/IPTC/Photoshop/comment metadata remains')
            entry = audit_files[asset['file_path']]
            if asset['sha256'] != entry['sha256_after']:
                raise ValueError('Metadata audit final SHA-256 mismatch')
            if entry['decoded_rgb_sha256_before'] != entry['decoded_rgb_sha256_after'] or entry['jpeg_scan_sha256_before'] != entry['jpeg_scan_sha256_after']:
                raise ValueError('Metadata removal was not lossless')
            if jpeg_scan_sha256(blob) != entry['jpeg_scan_sha256_after'] or protected_segments_sha256(blob) != entry['protected_segments_sha256_after']:
                raise ValueError('Compressed scan or color-management segments differ from audit')
            if asset['sha256'] in hashes:
                raise ValueError('Duplicate image bytes')
            hashes.add(asset['sha256'])
            if len(blob) > 2 * 1024 * 1024:
                raise ValueError('Photo exceeds 2 MiB publishing budget')
            with Image.open(path) as image:
                if list(image.size) != asset['image_dimensions']:
                    raise ValueError('Dimensions mismatch')
                if hashlib.sha256(image.convert('RGB').tobytes()).hexdigest() != entry['decoded_rgb_sha256_after']:
                    raise ValueError('Decoded RGB differs from metadata audit')
            with Image.open(path) as image:
                image.verify()
            evidence = json.loads((ROOT / asset['license_evidence_path']).read_text(encoding='utf-8'))
            if evidence['title'] != asset['source_title']:
                raise ValueError('Source evidence mismatch')
            if not asset['license_url'] or not asset['attribution']:
                raise ValueError('License URL or attribution missing')
            if asset['training_ready'] or asset['is_company_photo'] or asset['repair_pair_id'] is not None or asset['verified_repaired'] is not None:
                raise ValueError('Unverified enterprise/training/repair claim')
            source_id = 'commons-' + str(evidence['pageid'])
            sources.append({'source_id':source_id,'title':asset['source_title'],'url':asset['source_page_url'],'publisher':'Wikimedia Commons / named photographer or archive','checked_on':asset['license_evidence_checked_on'],'kind':'open_licensed_photo','revision_url':asset['source_page_revision_url']})
            photos.append({
                'photo_id':asset['asset_id'],'source_id':source_id,
                'original_url':asset['original_image_url'],
                'relative_path':asset['file_path'],'sha256':asset['sha256'],
                'equipment_category':asset['equipment_category'],
                'source_reported_condition':asset['source_reported_condition'],
                'observation':asset['domain_note'],
                'license_id':asset['license'],'attribution':asset['attribution'],
                'split_group':asset['split_group'],'company_image':0,
                'annotation_status':'unreviewed','training_approved':0,'paired_photo_id':None,
            })
        except Exception as error:
            errors.append({'asset':asset['asset_id'],'error':str(error)})
    contact_path = ROOT / 'contact_sheet.jpg'
    if contact_path.exists():
        try:
            contact_blob = contact_path.read_bytes()
            if optional_metadata(contact_blob):
                raise ValueError('Contact sheet contains optional metadata')
            if hashlib.sha256(contact_blob).hexdigest() != audit_files['contact_sheet.jpg']['sha256_after']:
                raise ValueError('Contact-sheet bytes differ from lossless audit')
        except Exception as error:
            errors.append({'asset':'contact_sheet.jpg','error':str(error)})
    report = {
        'assets':len(document['assets']),'verified':len(photos),'errors':errors,
        'total_image_bytes':sum((ROOT / a['file_path']).stat().st_size for a in document['assets'] if (ROOT / a['file_path']).exists()),
        'categories':dict(collections.Counter(a['equipment_category'] for a in document['assets'])),
        'licenses':dict(collections.Counter(a['license'] for a in document['assets'])),
        'split_groups':len({a['split_group'] for a in document['assets']}),
        'expert_approved':0,'company_photos':0,'verified_before_after_pairs':0,
        'optional_metadata_absent':not any('metadata' in e['error'].lower() for e in errors),
        'metadata_sanitized_files':audit['changed_files'],
        'lossless_rgb_and_scan_audit_verified':not errors,
        'qa_scope':'file integrity, lossless metadata removal, source/license metadata, safe provenance flags; expert defect annotation is pending',
    }
    (ROOT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not errors:
        (ROOT / 'database_import.json').write_text(json.dumps({'reference_sources':sources,'training_photos':photos}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    if errors:
        raise SystemExit(1)
    # Verification never rewrites photographs or the existing contact sheet.

if __name__ == '__main__':
    main()
