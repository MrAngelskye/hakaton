"""Read-only fixture verification, using only the Python standard library."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def verify(directory):
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    data=json.loads((directory/'demo.json').read_text(encoding='utf-8'))
    required={'sites':4,'equipment':25,'brigades':3,'defect_codes':20,'materials':40}
    for table,minimum in required.items():
        if len(data[table])<minimum: raise ValueError('Insufficient '+table)
    if sum(u['role']=='master' for u in data['users'])<2 or sum(u['role']=='worker' for u in data['users'])<15:
        raise ValueError('Insufficient masters/workers')
    if manifest['counts']['tasks']<500: raise ValueError('Insufficient tasks')
    for photo in data['task_photos']:
        key=photo['object_key']
        if Path(key).name!=key: raise ValueError('Unsafe photo key')
        file=directory/'photos'/key
        if hashlib.sha256(file.read_bytes()).hexdigest()!=photo['sha256']: raise ValueError('Photo mismatch: '+key)
        if file.stat().st_size!=photo['byte_size']: raise ValueError('Photo size mismatch: '+key)
    with sqlite3.connect((directory/'naryadai.db').resolve().as_uri()+'?mode=ro',uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SQLite integrity failure')
        if c.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Foreign key failure')
        for table in required.keys()|{'users','tasks','reports','events','pauses','ai_jobs','report_materials','task_photos','equipment_downtimes'}:
            count=c.execute('SELECT count(*) FROM '+table).fetchone()[0]
            if count!=manifest['counts'][table]: raise ValueError('Manifest mismatch: '+table)
        wrong=c.execute('SELECT count(*) FROM reports r JOIN tasks t ON t.id=r.task_id WHERE r.worker_id<>t.worker_id').fetchone()[0]
        if wrong: raise ValueError('Report worker mismatch')
        duplicates=c.execute('SELECT sha256,count(*) FROM task_photos GROUP BY sha256 HAVING count(*)>1').fetchall()
        if duplicates: raise ValueError('Duplicate synthetic image content')
        times=c.execute('SELECT count(*) FROM reports WHERE reviewed IS NOT NULL AND reviewed<created').fetchone()[0]
        if times: raise ValueError('Invalid report chronology')
        missing=c.execute("SELECT count(*) FROM reports r WHERE r.status='approved' AND NOT EXISTS(SELECT 1 FROM task_photos p WHERE p.report_id=r.id AND p.kind='after')").fetchone()[0]
        if missing: raise ValueError('Missing after image')
        event_sequences=c.execute('SELECT task_id,from_status,to_status FROM events ORDER BY task_id,created,id').fetchall()
        previous={}
        for tid,old,new in event_sequences:
            if tid in previous and old!=previous[tid]: raise ValueError('Broken event chain: '+str(tid))
            previous[tid]=new
        patterns={
            'conveyor_unplanned_repairs':c.execute('SELECT unplanned_repairs FROM equipment_failures WHERE id=1').fetchone()[0],
            'pump_oil_leaks':c.execute("SELECT count(*) FROM reports r JOIN tasks t ON t.id=r.task_id WHERE r.status='approved' AND t.equipment_id=7 AND r.defect_code_id=9").fetchone()[0],
            'worker15_late_reports':c.execute("SELECT closed_tasks-on_time_tasks FROM employee_metrics WHERE username='worker15'").fetchone()[0],
            'conveyor_grease_quantity':c.execute("SELECT avg(rm.quantity) FROM report_materials rm JOIN reports r ON r.id=rm.report_id JOIN tasks t ON t.id=r.task_id WHERE r.status='approved' AND rm.material_id=16 AND t.equipment_id=1").fetchone()[0],
        }
        if patterns['conveyor_unplanned_repairs']<80 or patterns['pump_oil_leaks']<30 or patterns['worker15_late_reports']<40 or patterns['conveyor_grease_quantity']!=3:
            raise ValueError('One of the planted patterns is missing')
    return {'status':'passed','synthetic':True,'counts':manifest['counts'],'patterns':patterns,'photos_verified':len(data['task_photos'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'generated')
    args=parser.parse_args(); print(json.dumps(verify(args.data_dir.resolve()),ensure_ascii=False,indent=2))
