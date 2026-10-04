"""Apply reviewed source replacements to cloud-1.4, with checks and backups."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def apply(project):
    project=project.resolve(strict=True)
    specification=json.loads((ROOT/'integration_changes.json').read_text(encoding='utf-8'))
    staged=[]
    for change in specification['files']:
        target=(project/change['path']).resolve()
        if not target.is_relative_to(project): raise ValueError('File path escapes project directory.')
        original=target.read_bytes()
        # Git on Windows may have converted LF to CRLF.
        normalized=original.decode('utf-8-sig').replace('\r\n','\n').rstrip('\n')+'\n'
        normalized_hash=hashlib.sha256(normalized.encode()).hexdigest()
        if normalized_hash==change['after_sha256']:
            print('Already applied:',change['path']); continue
        if normalized_hash!=change['before_sha256']:
            raise ValueError('Source differs from reviewed cloud-1.4: '+change['path']+'. No files changed; merge manually using integration.patch.')
        updated=normalized
        for edit in change['replacements']:
            if updated.count(edit['before'])!=1: raise ValueError('Expected unique source fragment: '+change['path'])
            updated=updated.replace(edit['before'],edit['after'],1)
        if hashlib.sha256(updated.encode()).hexdigest()!=change['after_sha256']: raise ValueError('Patch hash mismatch.')
        if target.suffix=='.py': compile(updated,str(target),'exec')
        backup=target.with_name(target.name+'.before-db-integration')
        if backup.exists() and backup.read_bytes()!=original: raise ValueError('A different backup already exists: '+str(backup))
        temporary=target.with_name(target.name+'.db-integration.tmp')
        if temporary.exists(): raise ValueError('Temporary file already exists: '+str(temporary))
        staged.append((target,backup,temporary,original,updated.encode('utf-8')))
    changed=[]
    try:
        for target,backup,temporary,original,updated in staged:
            if not backup.exists():
                with backup.open('xb') as f: f.write(original)
            with temporary.open('xb') as f: f.write(updated)
            os.replace(temporary,target); changed.append((target,original))
            print('Updated:',target.relative_to(project))
    except Exception:
        for target,original in changed: target.write_bytes(original)
        for _,_,temporary,_,_ in staged:
            if temporary.exists(): temporary.unlink()
        raise
    print('Source integration complete. Backups have suffix .before-db-integration.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir',required=True,type=Path,help='Folder containing app/ and server/')
    args=parser.parse_args(); apply(args.project_dir)
