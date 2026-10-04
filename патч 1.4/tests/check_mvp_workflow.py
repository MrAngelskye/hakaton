"""Изолированные headless проверки MVP: python tests/check_mvp_workflow.py."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, STATUS
from app.domain import company_time


class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.store=Store(self.root)
        self.master=self.store.authenticate('master','1234','master')
        self.worker=self.store.authenticate('worker4','1234','worker')
        self.other=self.store.authenticate('worker3','1234','worker')
        self.admin=self.store.authenticate('admin','1234','admin')
        self.day='2040-10-08'

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **updates):
        values=dict(title='Проверить исправность компрессора',description='Осмотреть привод и выполнить контрольный запуск.',
                    site='Ремонтный участок',equipment='Компрессор КМ-07',priority='normal',kind='Плановая',
                    duration=1,day=self.day,start=10,deadline=self.day+'T18:00',worker_id=self.worker['id'],issued=True)
        values.update(updates)
        return self.store.create_task(self.master,**values)

    def report(self, tid, **updates):
        values=dict(work='Проверены крепления, очищен привод, проведён контрольный запуск.',result='Контрольный запуск: замечаний нет.',
                    defect='D-03 · Загрязнение',hours=1,materials=[],photo_sources=[])
        values.update(updates)
        return self.store.submit(self.worker,tid,**values)

    def test_explicit_acceptance_and_full_human_review(self):
        tid=self.create()
        self.assertEqual(self.store.task(self.worker,tid)['status'],'issued')
        with self.assertRaises(ValueError):self.store.transition(self.worker,tid,'inProgress')
        with self.assertRaises(PermissionError):self.store.transition(self.other,tid,'accepted')
        self.store.transition(self.worker,tid,'accepted');self.store.transition(self.worker,tid,'queued')
        self.store.transition(self.worker,tid,'inProgress');self.store.transition(self.worker,tid,'paused','Нет расходных материалов')
        self.store.transition(self.worker,tid,'inProgress');rid=self.report(tid)
        self.assertIsNotNone(self.store.task(self.worker,tid)['completed_at'])
        self.store.review(self.master,rid,False,None,'Уточнить результат контрольного запуска')
        self.assertIsNone(self.store.task(self.worker,tid)['completed_at'])
        self.store.transition(self.worker,tid,'inProgress');rid2=self.report(tid)
        self.store.review(self.master,rid2,True,92,'Работа подтверждена мастером')
        self.assertEqual(self.store.task(self.worker,tid)['status'],'approved')
        self.assertIsInstance(self.store.latest_report(self.worker,tid)['checks'],list)
        self.assertTrue(all(e['actor_id'] and e['created'] for e in self.store.events(self.master,tid)))

    def test_legacy_and_four_priorities(self):
        for i,priority in enumerate(('urgent','high','normal','routine')):
            tid=self.create(start=8+i,priority=priority,issued=False)
            self.assertEqual(self.store.task(self.worker,tid)['status'],'planned')
        self.store.transition(self.worker,tid,'inProgress')
        with self.assertRaises(ValueError):self.create(start=14,priority='unknown')
        self.assertIn('rejected',STATUS)

    def test_rejection_reassignment_and_no_overlap(self):
        tid=self.create()
        with self.assertRaises(ValueError):self.store.transition(self.worker,tid,'rejected',' ')
        self.store.transition(self.worker,tid,'rejected','Нет допуска к оборудованию')
        second=self.create()
        self.assertEqual(self.store.task(self.master,tid)['rejected_reason'],'Нет допуска к оборудованию')
        with self.assertRaises(PermissionError):self.store.reassign_task(self.worker,tid,self.other['id'],self.day,12,'Замена исполнителя')
        self.store.reassign_task(self.master,tid,self.other['id'],self.day,12,'Замена исполнителя')
        with self.assertRaises(PermissionError):self.store.task(self.worker,tid)
        self.assertEqual(self.store.task(self.other,tid)['status'],'issued')
        self.store.transition(self.worker,second,'accepted');self.store.transition(self.worker,second,'inProgress')
        with self.assertRaises(ValueError):self.store.reassign_task(self.master,second,self.other['id'],self.day,14,'Замена после старта')

    def test_reference_data_crud_links_and_permissions(self):
        data=self.store.references(self.master)
        self.assertEqual([len(data[k]) for k in ('sites','equipment','brigades','defects','materials')],[4,25,3,20,40])
        self.assertEqual(len([u for u in self.store.users(self.master) if u['role']=='worker']),15)
        self.assertEqual(len([u for u in self.store.users(self.master) if u['role']=='master']),2)
        self.assertTrue(all(item['demo'] for values in data.values() for item in values))
        self.assertEqual({item['code'].split('-')[0] for item in data['defects']},{'М','Э','Г','П','С'})
        self.assertTrue(all(x['site_id']==data['sites'][0]['id'] for x in self.store.references(self.worker,'equipment',data['sites'][0]['id'])))
        with self.assertRaises(PermissionError):self.store.save_reference(self.master,'sites',{'name':'Новый участок'})
        site=self.store.save_reference(self.admin,'sites',{'name':'Демо: новый участок'})
        equipment=self.store.save_reference(self.admin,'equipment',{'name':'Демо: новый компрессор','site_id':site['id']})
        brigade=self.store.save_reference(self.admin,'brigades',{'name':'Демо: новая бригада','members':[self.worker['id']]})
        normative=self.store.save_reference(self.admin,'normatives',{'name':'Демо: осмотр компрессора','hours':1})
        with self.assertRaises(ValueError):self.create(site=site['name'])
        with self.assertRaises(ValueError):self.create(equipment='Оборудование без справочника')
        with self.assertRaises(ValueError):self.create(site=site['name'],equipment=equipment['name'],brigade_id=brigade['id'],worker_id=self.other['id'])
        tid=self.create(site=site['name'],equipment=equipment['name'],brigade_id=brigade['id'],normative_id=normative['id'])
        with self.assertRaises(ValueError):self.store.delete_reference(self.admin,'equipment',equipment['id'])
        with self.assertRaises(ValueError):self.store.save_reference(self.admin,'equipment',{**equipment,'active':False})
        self.store.transition(self.master,tid,'cancelled')
        self.store.delete_reference(self.admin,'equipment',equipment['id'])
        self.assertNotIn(equipment['id'],[r['id'] for r in self.store.references(self.worker,'equipment')])
        self.assertTrue(any(r['id']==equipment['id'] and not r['active'] for r in self.store.references(self.admin,'equipment')))
        self.assertEqual(self.store.task(self.master,tid)['equipment'],equipment['name'])

    def test_deadline_alerts_persist_stop_after_submission(self):
        tid=self.create(deadline=self.day+'T11:00')
        with self.store.transaction() as c:c.execute('UPDATE tasks SET issued_at=? WHERE id=?',(self.day+'T10:00:00',tid))
        own=lambda at:[a for a in self.store.alerts(self.master,at) if a['task_id']==tid]
        self.assertFalse(own(self.day+'T10:09:59'))
        self.assertEqual(own(self.day+'T10:10')[0]['kind'],'not_accepted')
        self.assertEqual(len([a for a in own(self.day+'T10:10') if a['kind']=='not_accepted']),1)
        self.store.transition(self.worker,tid,'accepted')
        self.assertFalse(own(self.day+'T10:20'))
        self.assertEqual(own(self.day+'T10:30')[0]['kind'],'deadline')
        self.assertEqual(own(self.day+'T11:01')[0]['kind'],'overdue')
        again=Store(self.root)
        self.assertTrue(any(a['task_id']==tid and a['kind']=='overdue' for a in again.alerts(self.worker,self.day+'T11:01')))
        self.assertFalse(any(a['task_id']==tid for a in again.alerts(self.other,self.day+'T11:01')))
        self.store.transition(self.worker,tid,'inProgress');self.report(tid)
        self.assertFalse(own(self.day+'T11:10'))
        with self.store.transaction() as c:c.execute("UPDATE tasks SET status='aiPending' WHERE id=?",(tid,))
        self.assertFalse(own(self.day+'T12:00'))

    def test_urgent_escalation_timezone_shift_and_settings(self):
        tid=self.create(priority='urgent')
        with self.store.transaction() as c:c.execute('UPDATE tasks SET issued_at=? WHERE id=?',(self.day+'T07:00',tid))
        own=lambda at:[a for a in self.store.alerts(self.master,at) if a['task_id']==tid]
        self.assertFalse(own(self.day+'T08:02:59'))
        self.assertEqual(own(self.day+'T03:03:00+00:00')[0]['kind'],'not_accepted')
        with self.assertRaises(PermissionError):self.store.set_notification_settings(self.master,urgent_accept_minutes=5)
        with self.assertRaises(ValueError):self.store.set_notification_settings(self.admin,accept_minutes=0)
        self.store.set_notification_settings(self.admin,urgent_accept_minutes=5)
        self.assertFalse(own(self.day+'T08:04'))
        self.assertTrue(own(self.day+'T08:05'))
        self.assertEqual(self.store.notification_settings(self.admin)['timezone'],'Asia/Qyzylorda')

    def test_work_and_pause_timing_equipment_card(self):
        tid=self.create()
        def stamp(value):return patch('app.domain.local_stamp',return_value=self.day+'T'+value)
        self.store.transition(self.worker,tid,'accepted')
        with stamp('10:00:00'):self.store.transition(self.worker,tid,'inProgress')
        with stamp('10:30:00'):self.store.transition(self.worker,tid,'paused','Нет материалов')
        # Pause timestamps use app.store.now, so set the same clock there.
        with self.store.transaction() as c:c.execute('UPDATE pauses SET started=? WHERE task_id=?',(self.day+'T10:30:00',tid))
        with stamp('10:45:00'),patch('app.store.now',return_value=self.day+'T10:45:00'):self.store.transition(self.worker,tid,'inProgress')
        with stamp('11:00:00'),patch('app.store.now',return_value=self.day+'T11:00:00'):self.report(tid)
        card=self.store.equipment_history(self.master,'Компрессор КМ-07')
        task=next(t for t in card['tasks'] if t['id']==tid)
        self.assertEqual(task['work_minutes'],45);self.assertEqual(task['pause_minutes'],15)
        self.assertTrue(task['timing_recorded'])
        self.assertIn('не подтверждённый простой',task['timing_note'])
        with self.assertRaises(PermissionError):self.store.attention(self.worker)

    def test_migration_preserves_existing_data_and_photos(self):
        legacy=self.create(issued=False)
        marker=self.store.photos/'keep.txt';marker.write_text('keep')
        with self.store.transaction() as c:
            before=c.execute('SELECT count(*) FROM tasks').fetchone()[0]
            c.execute('ALTER TABLE tasks DROP COLUMN issued_at')
            c.execute('ALTER TABLE reports DROP COLUMN checks')
        again=Store(self.root)
        self.assertTrue(marker.exists());self.assertEqual(again.task(self.worker,legacy)['status'],'planned')
        with again.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],before)
            self.assertIn('checks',again._columns(c,'reports'))

    def test_legacy_reassignment_preserves_unknown_equipment_labels(self):
        tid=self.create(issued=False)
        with self.store.transaction() as c:
            c.execute('UPDATE tasks SET site=?,equipment=? WHERE id=?',('Исторический участок','Исторический стенд',tid))
        self.store.reassign_task(self.master,tid,self.other['id'],self.day,12,'Замена исполнителя исторической работы')
        task=self.store.task(self.other,tid)
        self.assertEqual((task['site'],task['equipment'],task['status']),('Исторический участок','Исторический стенд','issued'))
        with self.assertRaises(ValueError):self.create(site=task['site'],equipment=task['equipment'])


if __name__=='__main__':
    unittest.main(verbosity=2)
