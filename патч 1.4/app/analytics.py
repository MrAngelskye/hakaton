"""Explainable period/shift analytics. No model-generated SQL or hidden penalties."""
from collections import defaultdict
from datetime import date,datetime,timedelta
from app.case_store import moment,stamp,decoded

WEIGHTS={'quality':.4,'on_time':.25,'no_rework':.15,'volume':.15,'justified_refusals':.05}

def period_analytics(store,actor,start,end,site_id=None,equipment_id=None,worker_id=None,brigade_id=None):
    begin,finish=moment(start),moment(end)
    if finish<=begin or finish-begin>timedelta(days=366):raise ValueError('Период: больше 0, не больше 366 суток. Конец не включён.')
    with store.transaction() as c:
        user=store.require(c,actor)
        if user['role']=='worker' and worker_id not in (None,user['id']):raise PermissionError('Доступен только собственный рейтинг.')
        if user['role']=='worker':worker_id=user['id']
        tasks=store.tasks(actor);people=store.users(actor,True)
        args=();where=''
        if user['role']=='worker':where=' WHERE r.worker_id=?';args=(user['id'],)
        reports=[dict(r) for r in c.execute('SELECT r.id,r.task_id,r.worker_id,r.brigade_id,r.status,r.score,r.hours,r.completed_at,r.data_origin,r.materials,r.defect_code_id FROM reports r'+where,args)]
        for r in reports:r['materials']=decoded(r['materials'],[])
        def matches(t):
            return (not site_id or t['site_id']==site_id) and (not equipment_id or t['equipment_id']==equipment_id)
        taskmap={t['id']:t for t in tasks if matches(t)}
        def owned(t):
            return (not worker_id or t['worker_id']==worker_id) and (not brigade_id or t['brigade_id']==brigade_id)
        def inside(value):return bool(value and begin<=moment(value)<finish)
        selected=[t for t in taskmap.values() if owned(t)]
        done=[r for r in reports if r['status']=='approved' and r['task_id'] in taskmap and inside(r['completed_at']) and (not worker_id or r['worker_id']==worker_id) and (not brigade_id or r['brigade_id']==brigade_id)]
        refusals_all=[dict(r) for r in c.execute('SELECT * FROM task_refusals WHERE created_at>=? AND created_at<?',(begin.isoformat(),finish.isoformat())) if r['task_id'] in taskmap and (not worker_id or r['worker_id']==worker_id) and (not brigade_id or r['brigade_id']==brigade_id)]
        assigned={r['task_id'] for r in done}
        returns={r['task_id'] for r in reports if r['task_id'] in assigned and r['status']=='superseded'}
        repeats={t['repeat_of_task_id'] for t in taskmap.values() if t['repeat_confirmed_by'] and t['repeat_of_task_id'] in assigned}
        count={'issued':sum(inside(t['issued_at']) for t in selected),'completed':len(done),'closed':sum(inside(t['closed_at']) for t in selected),
               'rejected':len({r['task_id'] for r in refusals_all}),'overdue':0,
               'completed_late':sum(moment(r['completed_at'])>moment(taskmap[r['task_id']]['deadline']) for r in done)}
        # Status at a historical boundary is reconstructed from recorded transitions.
        if selected:
            ids=[t['id'] for t in selected];placeholders=','.join('?' for _ in ids)
            events=c.execute('SELECT task_id,to_status,created FROM events WHERE task_id IN ('+placeholders+') AND created<? AND to_status IS NOT NULL ORDER BY created,id',tuple(ids)+(finish.isoformat(),)).fetchall()
            states={t['id']:('approved' if t['closed_at'] and moment(t['closed_at'])<finish else 'submitted' if t['completed_at'] and moment(t['completed_at'])<finish else 'unknown') if t['data_origin']!='recorded' else 'planned' if t['worker_id'] else 'available' for t in selected if moment(t['created'])<finish}
            for event in events:states[event['task_id']]=event['to_status']
            count['status_at_end']=dict((status,list(states.values()).count(status)) for status in sorted(set(states.values())))
            count['overdue']=sum(moment(t['deadline'])<finish and states.get(t['id']) not in ('approved','cancelled','submitted','aiPending') and (not t['completed_at'] or moment(t['completed_at'])>=finish) for t in selected if moment(t['issued_at'])<finish)
        rankings=[]
        for person in people:
            if worker_id and person['id']!=worker_id:continue
            rr=[r for r in done if r['worker_id']==person['id']]
            refusals=[r for r in refusals_all if r['worker_id']==person['id'] and r['justified'] is not None]
            n=len(rr);tidset={r['task_id'] for r in rr}
            components={'quality':sum(r['score'] for r in rr)/n if n else None,
              'on_time':100*sum(moment(r['completed_at'])<=moment(taskmap[r['task_id']]['deadline']) for r in rr)/n if n else None,
              'no_rework':100*(1-len(tidset&(returns|repeats))/n) if n else None,
              'volume':sum(taskmap[r['task_id']]['complexity'] for r in rr),
              'justified_refusals':100*(1-sum(t['justified']==0 for t in refusals)/max(1,n+len(refusals))) if n else None}
            rankings.append({**person,'done':n,'hours':sum(r['hours'] for r in rr),'quality_score':components['quality'],'components':components,
               'legacy_times':sum(r['data_origin']!='recorded' for r in rr),'unassessed_refusals':sum(r['worker_id']==person['id'] and r['justified'] is None for r in refusals_all),
               'reworked_tasks':len(tidset&returns),'confirmed_repeat_tasks':len(tidset&repeats),
               'active_count':sum(t['worker_id']==person['id'] and t['status'] not in ('approved','cancelled') for t in tasks)})
        maximum=max((r['components']['volume'] for r in rankings),default=0)
        for rank in rankings:
            rank['complexity_volume']=rank['components']['volume']
            rank['components']['volume']=100*rank['complexity_volume']/maximum if maximum else None
            rank['score']=round(sum(rank['components'][key]*weight for key,weight in WEIGHTS.items()),2) if rank['done'] else None
        rankings.sort(key=lambda r:r['score'] if r['score'] is not None else -1,reverse=True)
        brigade=defaultdict(lambda:{'done':0,'weighted_score':0,'hours':0,'complexity_volume':0,'task_ids':set()})
        rankbyid={r['id']:r for r in rankings}
        for r in done:
            if r['brigade_id'] is None:continue
            item=brigade[r['brigade_id']];item['done']+=1;item['hours']+=r['hours'];item['complexity_volume']+=taskmap[r['task_id']]['complexity'];item['task_ids'].add(r['task_id'])
            item['weighted_score']+=rankbyid[r['worker_id']]['score'] or 0
        brigade_names={r['id']:r['name'] for r in c.execute('SELECT id,name FROM brigades')}
        brigades=[{'brigade_id':bid,'name':brigade_names.get(bid,f'Бригада {bid}'),'done':v['done'],'hours':v['hours'],'complexity_volume':v['complexity_volume'],'score':round(v['weighted_score']/v['done'],2),'task_ids':sorted(v['task_ids'])} for bid,v in brigade.items()]
        problems=defaultdict(lambda:{'repairs':0,'task_ids':[]})
        for r in done:
            t=taskmap[r['task_id']]
            if t['kind']=='Внеплановая':
                key=(t['equipment_id'],r['defect_code_id']);problems[key]['repairs']+=1;problems[key]['task_ids'].append(t['id'])
        failures=[{'equipment_id':key[0],'defect_code_id':key[1],**v} for key,v in problems.items()]
        intervals=defaultdict(list);downtimes=[]
        for r in c.execute('SELECT * FROM equipment_downtimes WHERE started_at<? AND (ended_at IS NULL OR ended_at>?)',(finish.isoformat(),begin.isoformat())):
            if r['task_id'] not in taskmap:continue
            t=taskmap[r['task_id']]
            if not owned(t):continue
            a,b=max(begin,moment(r['started_at'])),min(finish,moment(r['ended_at']) if r['ended_at'] else min(finish,moment(stamp())))
            if b>a:intervals[r['equipment_id']].append((a,b));downtimes.append(dict(r))
        totals=[]
        for eid,spans in intervals.items():
            spans.sort();merged=[]
            for a,b in spans:
                if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else:merged.append((a,b))
            totals.append({'equipment_id':eid,'hours':round(sum((b-a).total_seconds() for a,b in merged)/3600,3),'merged_intervals':[[a.isoformat(),b.isoformat()] for a,b in merged]})
        consumption=defaultdict(lambda:{'quantity':0,'cost':0,'task_ids':set()});overuse=[]
        for r in done:
            for line in r['materials']:
                key=(line.get('material_id'),line['name'],line['unit']);item=consumption[key];item['quantity']+=line['quantity'];item['cost']+=line['quantity']*line['price'];item['task_ids'].add(r['task_id'])
        norms={(r['norm_id'],r['material_id']):r['quantity'] for r in c.execute('SELECT * FROM material_norms')}
        for r in done:
            per=defaultdict(float)
            for line in r['materials']:per[line.get('material_id')]+=line['quantity']
            for mid,qty in per.items():
                limit=norms.get((taskmap[r['task_id']]['norm_id'],mid))
                if limit and qty>limit:overuse.append({'task_id':r['task_id'],'report_id':r['id'],'material_id':mid,'actual':qty,'norm':limit,'ratio':round(qty/limit,3)})
        material=[{'material_id':key[0],'name':key[1],'unit':key[2],'quantity':round(v['quantity'],6),'cost':round(v['cost'],2),'task_ids':sorted(v['task_ids'])} for key,v in consumption.items()]
        return {'start':begin.isoformat(),'end_exclusive':finish.isoformat(),'counts':count,'weights':WEIGHTS,'workers':rankings,'brigades':brigades,'failures':sorted(failures,key=lambda r:-r['repairs']),
          'equipment_downtime':totals,'downtime_records':downtimes,'materials':material,'material_overuse':overuse,
          'coverage':{'legacy_completion_times':sum(r['data_origin']!='recorded' for r in done),'approved_reports':len(done),'rating_note':'Volume is normalized to the strongest worker in this filtered period. Only master-confirmed repeats and assessed refusals affect penalties. Legacy completion times are inferred from report submission.'}}
