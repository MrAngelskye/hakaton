"""Synthetic history checks, exclusively on temporary local databases."""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.domain import company_time
from tools.demo_history import create_demo_history,populate_demo_history,history_is_seeded,PATTERNS


class DemoHistoryChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_540_reports_intervals_repeated_patterns_and_no_ai_or_fake_photos(self):
        directory=self.root/'history';result=create_demo_history(directory)
        self.assertTrue(result['created']);self.assertEqual(result['count'],540)
        self.assertTrue(history_is_seeded(directory))
        store=Store(directory);master=store.authenticate('master','1234','master')
        with store.transaction() as c:
            tasks=[dict(t) for t in c.execute("SELECT * FROM tasks WHERE title LIKE 'Демо:%'")]
            self.assertEqual(len(tasks),540);self.assertEqual(len({t['day'] for t in tasks}),90)
            self.assertEqual(min(t['day'] for t in tasks),(company_time().date()-timedelta(days=90)).isoformat())
            self.assertEqual(max(t['day'] for t in tasks),(company_time().date()-timedelta(days=1)).isoformat())
            for t in tasks:
                self.assertEqual(t['status'],'approved')
                self.assertLess(company_time(t['actual_started']),company_time(t['completed_at']))
                self.assertLessEqual(company_time(t['completed_at']),company_time(t['deadline']))
                self.assertEqual(json.loads(c.execute('SELECT photos FROM reports WHERE task_id=?',(t['id'],)).fetchone()['photos']),[])
            self.assertEqual(c.execute('SELECT count(*) FROM work_sessions').fetchone()[0],540+sum(result['patterns'].values()))
            self.assertEqual(c.execute('SELECT count(*) FROM pauses').fetchone()[0],sum(result['patterns'].values()))
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='ai_jobs'").fetchone())
        for pattern in PATTERNS:
            card=store.equipment_history(master,pattern['equipment'])
            self.assertTrue(any(d['defect']==pattern['defect'] and d['count']>=2 for d in card['repeat_defects']))
            self.assertGreater(card['pause_minutes'],0)
        self.assertGreaterEqual(len(store.attention(master)['repeated_equipment']),4)
        self.assertFalse(list(store.photos.iterdir()))
        second=populate_demo_history(store,allow_demo=True)
        self.assertFalse(second['created'])
        self.assertEqual(second['count'],540)
        self.assertEqual(len([t for t in store.tasks(master) if t['title'].startswith('Демо:')]),540)

    def test_cli_refuses_existing_database_and_preserves_bytes(self):
        directory=self.root/'existing';store=Store(directory)
        before=hashlib.sha256(store.path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):create_demo_history(directory)
        self.assertEqual(before,hashlib.sha256(store.path.read_bytes()).hexdigest())
        directory2=self.root/'files';directory2.mkdir();(directory2/'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):create_demo_history(directory2)
        self.assertEqual((directory2/'keep.txt').read_text(),'keep')

    def test_explicit_demo_only_and_modified_seed_refused(self):
        store=Store(self.root/'demo')
        with self.assertRaises(ValueError):populate_demo_history(store)
        with store.transaction() as c:c.execute('UPDATE tasks SET title=? WHERE id=1048',('Реальная пользовательская запись',))
        with self.assertRaises(ValueError):populate_demo_history(store,allow_demo=True)
        self.assertFalse(history_is_seeded(self.root/'demo'))
        with store.transaction() as c:self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],17)

    def test_run_demo_history_new_marked_and_refuse_unmarked_before_app_creation(self):
        import run_demo
        directory=self.root/'web-history'
        arguments=['run_demo.py','--history','--data-dir',str(directory)]
        with patch.object(sys,'argv',arguments),patch('run_demo.uvicorn.run') as launch:
            run_demo.main()
        app=launch.call_args.args[0]
        self.assertFalse(app.state.store.settings.ai_enabled)
        self.assertTrue(history_is_seeded(directory))
        with app.state.store.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ai_jobs').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],557)
        with patch.object(sys,'argv',arguments),patch('run_demo.uvicorn.run') as relaunch:
            run_demo.main()
        with relaunch.call_args.args[0].state.store.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],557)
        old=Store(self.root/'existing-web')
        before=hashlib.sha256(old.path.read_bytes()).hexdigest()
        with patch.object(sys,'argv',['run_demo.py','--history','--data-dir',str(old.directory)]),patch('run_demo.create_app') as create:
            with self.assertRaises(SystemExit):run_demo.main()
        create.assert_not_called()
        self.assertEqual(before,hashlib.sha256(old.path.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main(verbosity=2)
