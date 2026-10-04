"""Synthetic 90-day history, only for a fresh isolated demo database.

No photo evidence or AI output is fabricated. Existing databases are refused by
the CLI; the internal explicit demo hook is idempotent after its own marker.
"""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.domain import company_time

MARKER = 'synthetic_history_seed'
PATTERNS = [
    {'equipment':'Конвейер ЛК-03','defect':'М-01 · Износ подшипника','reason':'Демо: ожидание замены подшипника',
     'hours':1.5,'pause_minutes':60,'description':'Условные повторные работы по износу конвейера'},
    {'equipment':'Грохот ГР-08','defect':'Э-04 · Неисправность датчика','reason':'Демо: ожидание сменного датчика',
     'hours':2,'pause_minutes':45,'description':'Условные повторные проверки датчика грохота'},
    {'equipment':'Аспирационная установка АУ-02','defect':'С-03 · Загрязнение','reason':'Демо: ожидание очистки фильтра',
     'hours':1,'pause_minutes':30,'description':'Условная периодическая очистка аспирации'},
    {'equipment':'Насос НС-15','defect':'Г-01 · Утечка гидравлического масла','reason':'Демо: ожидание уплотнения со склада',
     'hours':1.5,'pause_minutes':90,'description':'Условные утечки с ожиданием материалов'},
]


def history_is_seeded(directory):
    database = Path(directory).resolve()/'naryadai.db'
    if not database.is_file():
        return False
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as c:
            return c.execute('SELECT 1 FROM demo_metadata WHERE key=?',(MARKER,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _stamp(value):
    return value.replace(tzinfo=None).isoformat(timespec='seconds')


def _validate_dimensions(count,days):
    if (isinstance(count,bool) or not isinstance(count,int) or not 500<=count<=5000 or
        isinstance(days,bool) or not isinstance(days,int) or not 3<=days<=365 or count>days*15):
        raise ValueError('Демо-история: 500–5000 нарядов за 3–365 дней, не более 15 нарядов в день.')


def _pristine_demo(c):
    expected_users={'master','master2','admin'}|{f'worker{i}' for i in range(1,16)}
    if {u['username'] for u in c.execute('SELECT username FROM users')} != expected_users:
        return False
    expected_ids=set(range(1030,1038))|{1044,1045,1046,1047,1048,1049,1050,1051,1052}
    tasks=c.execute('SELECT * FROM tasks').fetchall()
    if {t['id'] for t in tasks} != expected_ids:
        return False
    baseline_titles={1048:'Проверить привод ленточного конвейера',1049:'Осмотреть гидравлическую систему экскаватора',
                     1050:'Обслужить компрессор ремонтного участка',1051:'Осмотреть систему аспирации',
                     1052:'Проверить сигнал датчика дробилки',1046:'Осмотреть ролики конвейера',
                     1047:'Проверить датчик вибрации грохота',1044:'Обслужить электропривод дробилки',
                     1045:'Проверить насос гидравлической системы'}
    for index in range(8):
        baseline_titles[1030+index]=['Осмотр электропривода','Проверка датчиков линии','Обслуживание узла'][index%3]
    if any(t['title']!=baseline_titles[t['id']] or t['actual_started'] for t in tasks):
        return False
    if c.execute('SELECT count(*) FROM events').fetchone()[0] != 17:
        return False
    if c.execute('SELECT count(*) FROM reports').fetchone()[0] != 10:
        return False
    if c.execute('SELECT count(*) FROM pauses').fetchone()[0] or c.execute('SELECT count(*) FROM work_sessions').fetchone()[0]:
        return False
    references=c.execute('SELECT payload,active FROM reference_items').fetchall()
    return len(references)==96 and all(json.loads(r['payload']).get('demo') and r['active'] for r in references)


def populate_demo_history(store, *, allow_demo=False, count=540, days=90):
    """Populate once, only after explicit authorisation of a pristine local demo.

    Returns marker data with created=False on a subsequent invocation. Not for
    PostgresStore, cloud data, existing real records, or a modified demo seed.
    """
    if not allow_demo or getattr(getattr(store,'settings',None),'database_url','') or hasattr(store,'storage'):
        raise ValueError('История разрешена только в отдельной локальной демо-базе с allow_demo=True.')
    _validate_dimensions(count,days)
    today=company_time().date()
    with store.transaction() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS demo_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        prior=c.execute('SELECT value FROM demo_metadata WHERE key=?',(MARKER,)).fetchone()
        if prior:
            return {**json.loads(prior['value']),'created':False}
        if not _pristine_demo(c):
            raise ValueError('База уже содержит изменения. Выберите новую папку для синтетической истории.')
        refs=store._references(c)
        sites={s['id']:s['name'] for s in refs['sites']}
        equipment=refs['equipment']; by_name={e['name']:e for e in equipment}
        workers=[u['id'] for u in c.execute("SELECT id FROM users WHERE role='worker' ORDER BY id")]
        masters=[u['id'] for u in c.execute("SELECT id FROM users WHERE role='master' ORDER BY id")]
        patterns={p['equipment']:0 for p in PATTERNS}
        for index in range(count):
            offset=index*days//count
            day=(today-timedelta(days=days-offset)).isoformat()
            slot=index%6
            pattern=None
            if slot==0 and offset%4 in (0,1):pattern=PATTERNS[0]
            elif slot==1 and offset%3==0:pattern=PATTERNS[1]
            elif slot==2 and offset%7 in (0,1):pattern=PATTERNS[2]
            elif slot==3 and offset%10 in (0,1):pattern=PATTERNS[3]
            eq=by_name[pattern['equipment']] if pattern else equipment[(index*7)%len(equipment)]
            worker=workers[index%len(workers)];master=masters[index%len(masters)]
            hours=pattern['hours'] if pattern else (.5,1,1.5)[index%3]
            pause_minutes=pattern['pause_minutes'] if pattern else 0
            start=8+slot
            actual=company_time(day+'T00:00')+timedelta(hours=start)
            end=actual+timedelta(hours=hours,minutes=pause_minutes)
            issued=actual-timedelta(minutes=5);accepted=actual-timedelta(minutes=2)
            defect=pattern['defect'] if pattern else 'Неисправность не обнаружена'
            reason=pattern['reason'] if pattern else ''
            title='Демо: '+('проверка повторной неисправности — ' if pattern else 'плановый осмотр — ')+eq['name']
            description='Синтетическая история для показа аналитики; не производственный факт. '+(pattern['description'] if pattern else 'Плановый осмотр оборудования.')
            cur=c.execute('''INSERT INTO tasks(title,description,site,equipment,priority,kind,duration,day,start,deadline,
              worker_id,master_id,status,created,issued_at,accepted_at,actual_started,completed_at)
              VALUES(?,?,?,?,?,'Плановая',?,?,?,?,?,?,'approved',?,?,?,?,?)''',
              (title,description,sites[eq['site_id']],eq['name'],'high' if pattern else 'routine',hours,day,start,day+'T18:00',
               worker,master,_stamp(issued),_stamp(issued),_stamp(accepted),_stamp(actual),_stamp(end)))
            tid=cur.lastrowid
            material=refs['materials'][index%len(refs['materials'])]
            used=[] if not pattern else [{'name':material['name'],'quantity':1,'unit':material['unit'],'price':0}]
            checks=[{'id':'synthetic_history','field':'work','severity':'info',
                     'message':'Демонстрационный исторический отчёт: фото отсутствуют, ИИ не запускался.'}]
            c.execute('''INSERT INTO reports(task_id,worker_id,work,result,defect,hours,materials,photos,status,score,
              comment,reviewer_id,created,reviewed,checks) VALUES(?,?,?,?,?,?,?,'[]','approved',?,?,?,?,?,?)''',
              (tid,worker,'Демо: осмотр и обслуживание узла в синтетическом сценарии.',
               'Демо: контрольная проверка завершена; результат условный.',defect,hours,json.dumps(used,ensure_ascii=False),
               82+index%16,'Демо: условная ручная приёмка мастером; не оценка модели.',master,
               _stamp(end),_stamp(end+timedelta(minutes=12)),json.dumps(checks,ensure_ascii=False)))
            if pause_minutes:
                patterns[eq['name']]+=1
                paused=actual+timedelta(hours=hours/2);resumed=paused+timedelta(minutes=pause_minutes)
                c.execute('INSERT INTO pauses(task_id,actor_id,reason,started,ended,ended_by) VALUES(?,?,?,?,?,?)',
                          (tid,worker,reason,_stamp(paused),_stamp(resumed),worker))
                c.execute('INSERT INTO work_sessions(task_id,actor_id,started,ended) VALUES(?,?,?,?)',(tid,worker,_stamp(actual),_stamp(paused)))
                c.execute('INSERT INTO work_sessions(task_id,actor_id,started,ended) VALUES(?,?,?,?)',(tid,worker,_stamp(resumed),_stamp(end)))
            else:
                c.execute('INSERT INTO work_sessions(task_id,actor_id,started,ended) VALUES(?,?,?,?)',(tid,worker,_stamp(actual),_stamp(end)))
            for actor,message,stamp in [(master,'Демо: наряд выдан',issued),(worker,'Демо: принят исполнителем',accepted),
                                        (worker,'Демо: работа начата',actual),(worker,'Демо: результат отправлен без ИИ',end),
                                        (master,'Демо: условная ручная приёмка',end+timedelta(minutes=12))]:
                c.execute('INSERT INTO events(task_id,actor_id,message,created) VALUES(?,?,?,?)',(tid,actor,message,_stamp(stamp)))
        marker={'synthetic':True,'count':count,'days':days,'start_day':(today-timedelta(days=days)).isoformat(),
                'end_day':(today-timedelta(days=1)).isoformat(),'patterns':patterns,
                'note':'Условные данные; паузы нарядов не подтверждают простой оборудования; фото и ИИ не имитируются.'}
        c.execute('INSERT INTO demo_metadata(key,value) VALUES(?,?)',(MARKER,json.dumps(marker,ensure_ascii=False)))
        return {**marker,'created':True}


def create_demo_history(directory, *, count=540, days=90):
    _validate_dimensions(count,days)
    directory=Path(directory).resolve()
    if (directory/'naryadai.db').exists() or (directory.exists() and (not directory.is_dir() or any(directory.iterdir()))):
        raise ValueError('Выберите новую пустую папку: существующая база и файлы не изменяются.')
    return populate_demo_history(Store(directory),allow_demo=True,count=count,days=days)


def main():
    parser=argparse.ArgumentParser(description='Отдельная синтетическая история НарядAI без фото и ИИ')
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'demo_history_data')
    parser.add_argument('--count',type=int,default=540);parser.add_argument('--days',type=int,default=90)
    args=parser.parse_args()
    try:result=create_demo_history(args.data_dir,count=args.count,days=args.days)
    except ValueError as error:parser.exit(2,str(error)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('Открыть: python run_demo.py --data-dir "'+str(args.data_dir.resolve())+'"')


if __name__=='__main__':main()
