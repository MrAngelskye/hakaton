import copy
import csv
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.store import Store
from app.production_data import bootstrap,import_photo_manifest,load_reference_package,make_credentials


class ProductionDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload=load_reference_package(ROOT.parent/'database/production/reference_catalog.json')
        cls.photos=json.loads((ROOT.parent/'database/production/photo_dataset/database_import.json').read_text(encoding='utf-8'))
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.store=Store(Path(self.directory.name)/'db',seed_demo=False)
    def tearDown(self):self.store.close();self.directory.cleanup()
    def populate(self):
        rows=make_credentials(self.payload)
        with self.store.transaction(write=True):
            result=bootstrap(self.store,self.payload,rows,include_catalogs=True);import_photo_manifest(self.store,self.photos)
        return result,rows
    def test_ai_reads_catalog_sources_without_inventing_prices_or_history(self):
        from server.knowledge import Knowledge
        from server.control import ControlCenter
        from server.config import Settings
        _,credentials=self.populate()
        account=next(row for row in credentials if row['role']=='admin')
        admin=self.store.authenticate(account['username'],account['password'],'admin')
        control=ControlCenter(self.store,Settings(data_dir=Path(self.directory.name),ai_enabled=False))
        facts=Knowledge(self.store,control).retrieve(admin,'Расскажи про подшипники SKF')
        self.assertEqual(facts['database_counts']['tasks'],0)
        self.assertTrue(facts['database_found'])
        self.assertLessEqual(len(facts['references']),5)
        materials=[r for r in facts['references'] if r['kind']=='material']
        self.assertTrue(materials)
        self.assertTrue(all(r['unit_price'] is None for r in materials))
        self.assertTrue(all(r['source']['url'].startswith('https://') for r in facts['references']))
        with self.assertRaises(PermissionError):
            worker=next(row for row in credentials if row['role']=='worker')
            Knowledge(self.store,control).retrieve(self.store.authenticate(worker['username'],worker['password'],'worker'),'подшипники SKF')

    def test_default_bootstrap_has_only_staff_and_no_operational_catalogs(self):
        credentials=make_credentials(self.payload)
        result=bootstrap(self.store,self.payload,credentials)
        self.assertEqual(result['users'],18)
        with self.store.transaction() as c:
            for table in ('tasks','reports','materials','sites','equipment','shifts','shift_rules','defect_codes','brigades','training_photos','work_order_templates'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        for row in credentials:
            self.assertTrue(self.store.authenticate(row['username'],row['password'],row['role']))
    def test_verified_refs_and_unique_credentials_without_fake_history(self):
        result,credentials=self.populate()
        self.assertEqual(result['users'],18)
        self.assertEqual(len({r['password'] for r in credentials}),18)
        for row in credentials:self.assertTrue(self.store.authenticate(row['username'],row['password'],row['role']))
        with self.store.transaction() as c:
            for table in ('tasks','reports','equipment','shift_rules','shifts','brigades'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
            self.assertEqual(c.execute('SELECT count(*) FROM training_photos').fetchone()[0],25)
            self.assertEqual(c.execute('SELECT count(*) FROM training_photos WHERE company_image<>0 OR training_approved<>0 OR paired_photo_id IS NOT NULL').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM material_reference_metadata WHERE price_known=0').fetchone()[0],26)
            self.assertEqual(c.execute("SELECT count(*) FROM work_order_templates WHERE status='draft'").fetchone()[0],20)
    def test_populated_catalog_is_refused_without_erasing_it(self):
        with self.store.transaction(write=True) as c:c.execute("INSERT INTO brigades(code,name) VALUES('existing','Existing brigade')")
        with self.assertRaises(ValueError):bootstrap(self.store,self.payload,make_credentials(self.payload))
        with self.store.transaction() as c:self.assertEqual(c.execute('SELECT name FROM brigades').fetchone()[0],'Existing brigade')
    def test_unreviewed_photo_cannot_be_approved_for_training(self):
        self.populate()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction(write=True) as c:c.execute("UPDATE training_photos SET training_approved=1 WHERE photo_id='open-maintenance-001'")
    def test_bad_photo_manifest_rolls_back_whole_bootstrap(self):
        photos=copy.deepcopy(self.photos);photos['training_photos'][0]['relative_path']='../outside.jpg'
        with self.assertRaises(ValueError):
            with self.store.transaction(write=True):
                bootstrap(self.store,self.payload,make_credentials(self.payload));import_photo_manifest(self.store,photos)
        with self.store.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM reference_sources').fetchone()[0],0)
    def test_credentials_survive_stdout_failure_after_commit(self):
        spec=importlib.util.spec_from_file_location('bootstrap_tool',ROOT/'tools/bootstrap_production.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        target=Path(self.directory.name)/'private.csv';db=Path(self.directory.name)/'cli-db'
        with patch.object(sys,'argv',['bootstrap','--sqlite-dir',str(db),'--credentials',str(target)]),patch('builtins.print',side_effect=BrokenPipeError):
            with self.assertRaises(BrokenPipeError):module.main()
        self.assertTrue(target.is_file())
        with target.open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
        with Store(db,seed_demo=False).transaction() as c:self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],len(rows))


if __name__=='__main__':unittest.main()
