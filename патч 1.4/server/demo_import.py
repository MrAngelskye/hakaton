"""Merge the bundled synthetic fixture with existing accounts. No destructive operations."""
import json,sqlite3,tempfile,zipfile
from pathlib import Path
from app.store import Store
ORDER=('sites','brigades','defect_codes','materials','users','equipment','work_norms','material_norms','shift_rules','shifts','tasks','reports','ai_jobs','events','pauses','brigade_memberships','task_assignments','task_photos','report_materials','equipment_downtimes','task_refusals')
ARCHIVE=Path(__file__).resolve().parents[2]/'database'/'naryadai_database.zip'

def read_demo_photo(name):
    import re
    if not re.fullmatch(r'demo_[a-f0-9]{32}\.jpg',name):raise FileNotFoundError(name)
    with zipfile.ZipFile(ARCHIVE) as z:
        try:return z.read('naryadai_database/generated/photos/'+name[5:])
        except KeyError:raise FileNotFoundError(name) from None

def prepare(source,target_columns,base):
    """Return deterministic, FK-consistent rows; source/target metadata supplied by trusted code."""
    rows={};mapping={};foreign={}
    for table in ORDER:
        rows[table]=[dict(r) for r in source.execute('SELECT * FROM '+table)]
        if table=='users':rows[table]=[row for row in rows[table] if row['role'] in ('worker','master','admin')]
        info=source.execute('PRAGMA table_info('+table+')').fetchall()
        if any(r['name']=='id' and r['pk'] for r in info):mapping[table]={r['id']:base+r['id'] for r in rows[table]}
        foreign[table]={r['from']:r['table'] for r in source.execute('PRAGMA foreign_key_list('+table+')') if r['to']=='id'}
    catalog_names={t:{r['name']:'Учебный · '+r['name'] for r in rows[t]} for t in ('sites','equipment','materials','brigades','defect_codes')}
    for table,items in rows.items():
        for row in items:
            original=row.get('id')
            for key,parent in foreign[table].items():
                if row.get(key) is not None and parent in mapping:row[key]=mapping[parent][row[key]]
            if table in mapping:row['id']=mapping[table][original]
            if 'data_origin' in row:row['data_origin']='synthetic'
            if table in catalog_names:row['name']=catalog_names[table][row['name']]
            if table=='tasks':
                row['site']=catalog_names['sites'].get(row['site'],row['site']);row['equipment']=catalog_names['equipment'].get(row['equipment'],row['equipment'])
            if table=='report_materials':row['name_snapshot']=catalog_names['materials'].get(row['name_snapshot'],row['name_snapshot'])
            if table=='users':row['username']='demo.'+row['username'];row['active']=0 if row['role'] in ('admin','master') else row['active']
            if table in ('sites','brigades','defect_codes','materials'):row['code']='DEMO-'+row['code']
            if table=='equipment':row['inventory_number']='DEMO-'+row['inventory_number']
            if table=='task_photos':row['object_key']='demo_'+row['object_key'];row['is_demo']=True
            if table=='reports':
                row['photos']=json.dumps(['demo_'+n for n in json.loads(row['photos'])],ensure_ascii=False)
                materials=json.loads(row['materials'])
                for material in materials:
                    material['name']=catalog_names['materials'].get(material['name'],material['name'])
                    if material.get('material_id') in mapping['materials']:material['material_id']=mapping['materials'][material['material_id']]
                row['materials']=json.dumps(materials,ensure_ascii=False)
                if row.get('defect_code_id'):
                    defect=next(d for d in rows['defect_codes'] if d['id']==row['defect_code_id'])
                    row['defect']=defect['code']
            if table=='events':
                data=json.loads(row['data']) if isinstance(row['data'],str) else row['data']
                for key,parent in {'report_id':'reports','worker_id':'users','previous_task_id':'tasks','downtime_id':'equipment_downtimes'}.items():
                    if isinstance(data.get(key),int) and data[key] in mapping.get(parent,{}):data[key]=mapping[parent][data[key]]
                row['data']=json.dumps(data,ensure_ascii=False)
            row.update({k:json.loads(v) for k,v in row.items() if target_columns[table].get(k) in ('json','jsonb') and isinstance(v,str)})
            for key,kind in target_columns[table].items():
                if kind=='boolean' and row.get(key) is not None:row[key]=bool(row[key])
            for key in list(row):
                if key not in target_columns[table]:del row[key]
    return rows

def merge(store,user,control):
    control.admin(user)
    if not getattr(store,'seed_demo',False):raise PermissionError('Импорт учебных данных отключён на рабочем сервере.')
    with zipfile.ZipFile(ARCHIVE) as z,tempfile.TemporaryDirectory(prefix='naryadai-fixture-') as temp:
        directory=Path(temp);manifest=json.loads(z.read('naryadai_database/generated/manifest.json'))
        if manifest.get('synthetic') is not True:raise ValueError('Архив не помечен как учебный.')
        (directory/'naryadai.db').write_bytes(z.read('naryadai_database/generated/naryadai.db'))
        Store(directory)  # Apply canonical migration to a disposable copy only.
        source=sqlite3.connect(directory/'naryadai.db');source.row_factory=sqlite3.Row
        try:
            with store.transaction(write=True) as c:
                marker=c.execute("SELECT value FROM service_settings WHERE key='demo_dataset'").fetchone()
                if marker:return json.loads(marker['value'])
                base=max(c.execute('SELECT COALESCE(MAX(id),0) AS n FROM '+t).fetchone()['n'] for t in ('users','tasks','reports','events','equipment'))+1000
                columns={}
                for t in ORDER:
                    if getattr(getattr(store,'settings',None),'database_url',''):
                        columns[t]={r['column_name']:r['data_type'] for r in c.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='naryadai' AND table_name=?",(t,))}
                    else:columns[t]={r['name']:r['type'].lower() for r in c.execute('PRAGMA table_info('+t+')')}
                rows=prepare(source,columns,base)
                if getattr(getattr(store,'settings',None),'database_url',''):
                    for t in ('tasks','reports','equipment_downtimes'):c.execute('ALTER TABLE '+t+' DISABLE TRIGGER USER')
                repeats=[]
                for t,items in rows.items():
                    for row in items:
                        if t=='tasks' and row.get('repeat_of_task_id'):repeat=row.pop('repeat_of_task_id');row['repeat_of_task_id']=None
                        else:repeat=None
                        keys=list(row);args=tuple(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for v in row.values())
                        c.execute('INSERT INTO '+t+'('+','.join('"'+k+'"' for k in keys)+') VALUES('+','.join('?' for _ in keys)+')',args)
                        if repeat:repeats.append((repeat,row['id']))
                for repeat,tid in repeats:c.execute('UPDATE tasks SET repeat_of_task_id=? WHERE id=?',(repeat,tid))
                if getattr(getattr(store,'settings',None),'database_url',''):
                    for t in ('tasks','reports','equipment_downtimes'):c.execute('ALTER TABLE '+t+' ENABLE TRIGGER USER')
                result={'dataset_id':manifest['dataset_id'],'users':len(rows['users']),'tasks':len(rows['tasks']),'reports':len(rows['reports']),'photos':len(rows['task_photos']),'synthetic':True,'base':base,'photo_storage':'bundled_demo_archive'}
                c.execute('INSERT INTO service_settings VALUES(?,?)',('demo_dataset',json.dumps(result)));control.audit(c,user,'demo_import',json.dumps(result))
                if getattr(getattr(store,'settings',None),'database_url',''):
                    for t in rows:
                        if rows[t] and 'id' in rows[t][0]:c.execute("SELECT setval(pg_get_serial_sequence(?, 'id'),(SELECT MAX(id) FROM "+t+"),true)",('naryadai.'+t,))
                return result
        finally:source.close()
