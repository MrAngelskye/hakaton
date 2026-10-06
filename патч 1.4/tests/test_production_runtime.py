"""Production startup must not invent staff, shifts, prices or work orders."""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.store import Store,password_hash
from server.config import Settings


EMPTY_TABLES=('users','sites','brigades','equipment','materials','defect_codes',
              'shift_rules','shifts','tasks','reports','events','task_photos','work_norms')


def administrator(store):
    """An isolated test account; never used by runtime seeding."""
    salt=secrets.token_hex(16)
    with store.transaction(write=True) as c:
        c.execute('INSERT INTO users(username,name,job,role,salt,password_hash) VALUES(?,?,?,?,?,?)',
                  ('isolated.admin','Тестовый администратор','Администратор','admin',salt,password_hash('Isolated-only-2026!',salt)))
    return store.authenticate('isolated.admin','Isolated-only-2026!','admin')


class ProductionRuntime(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_fresh_default_is_empty_and_repeat_start_is_empty(self):
        for _ in range(2):
            store=Store(self.directory)
            self.assertFalse(store.seed_demo)
            with store.transaction() as c:
                for table in EMPTY_TABLES:
                    self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
                self.assertGreater(c.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],0)
            store.close()

    def test_existing_accounts_and_catalogs_are_preserved_without_refilling_shifts(self):
        demo=Store(self.directory,seed_demo=True)
        with demo.transaction(write=True) as c:
            worker=c.execute("SELECT id FROM users WHERE username='worker1'").fetchone()[0]
            c.execute('DELETE FROM shift_rules WHERE worker_id=? AND weekday=0',(worker,))
            before={table:[tuple(row) for row in c.execute('SELECT * FROM '+table)] for table in EMPTY_TABLES}
        demo.close()
        for _ in range(2):
            store=Store(self.directory,seed_demo=False)
            with store.transaction() as c:
                after={table:[tuple(row) for row in c.execute('SELECT * FROM '+table)] for table in EMPTY_TABLES}
            self.assertEqual(after,before)
            # Preserving an existing database must not reset its existing credentials.
            self.assertEqual(store.authenticate('worker1','1234','worker')['id'],worker)
            store.close()

    def test_new_users_require_long_password_and_no_invented_schedule(self):
        store=Store(self.directory)
        admin=administrator(store)
        with self.assertRaises(ValueError):
            store.add_user(admin,'km.worker.01','Сотрудник 01','Электрослесарь','worker','1234')
        store.add_user(admin,'km.worker.01','Сотрудник 01','Электрослесарь','worker','Distinct-worker-2026!')
        worker=store.authenticate('km.worker.01','Distinct-worker-2026!','worker')
        with store.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM shift_rules WHERE worker_id=?',(worker['id'],)).fetchone()[0],0)
        profile=next(u for u in store.users(admin) if u['id']==worker['id'])
        self.assertFalse(profile['grade_confirmed'])
        self.assertEqual(profile['identity_status'],'user_entered')
        store.set_employee_profile(admin,worker['id'],'Электрослесарь',4)
        profile=next(u for u in store.users(admin) if u['id']==worker['id'])
        self.assertTrue(profile['grade_confirmed'])
        self.assertEqual(profile['grade'],4)
        with self.assertRaises(ValueError):store.reset_password(admin,worker['id'],'1234')
        store.reset_password(admin,worker['id'],'Replacement-worker-2026!')
        with self.assertRaises(ValueError):store.authenticate('km.worker.01','Distinct-worker-2026!','worker')
        self.assertEqual(store.authenticate('km.worker.01','Replacement-worker-2026!','worker')['id'],worker['id'])

    def test_settings_opt_in_is_typed_and_explicit(self):
        self.assertFalse(Settings(data_dir=self.directory).seed_demo)
        config=self.directory/'server.json'
        config.write_text(json.dumps({'data_dir':'runtime','ai_enabled':False}),encoding='utf-8')
        self.assertFalse(Settings.load(config).seed_demo)
        config.write_text(json.dumps({'data_dir':'runtime','ai_enabled':False,'seed_demo':True}),encoding='utf-8')
        self.assertTrue(Settings.load(config).seed_demo)
        config.write_text(json.dumps({'data_dir':'runtime','ai_enabled':False,'seed_demo':'false'}),encoding='utf-8')
        with self.assertRaises(ValueError):Settings.load(config)
        with self.assertRaises(ValueError):Store(self.directory/'invalid',seed_demo='false')

    def test_config_beats_demo_environment_and_invalid_opt_in_is_rejected(self):
        from unittest.mock import patch
        config=self.directory/'server.json'
        config.write_text(json.dumps({'data_dir':'runtime','ai_enabled':False}),encoding='utf-8')
        with patch.dict('os.environ',{'SEED_DEMO':'true'}):self.assertTrue(Settings.load(config).seed_demo)
        with patch.dict('os.environ',{'SEED_DEMO':'sometimes'}):
            with self.assertRaises(ValueError):Settings.load(config)
        config.write_text(json.dumps({'data_dir':'runtime','ai_enabled':False,'seed_demo':False}),encoding='utf-8')
        with patch.dict('os.environ',{'SEED_DEMO':'true'}):self.assertFalse(Settings.load(config).seed_demo)

    def test_public_catalog_price_and_grade_require_explicit_confirmation(self):
        store=Store(self.directory)
        admin=administrator(store)
        store.add_user(admin,'km.worker.01','Сотрудник 01','Электрослесарь','worker','Distinct-worker-2026!')
        worker=store.authenticate('km.worker.01','Distinct-worker-2026!','worker')
        with store.transaction(write=True) as c:
            c.execute('INSERT INTO reference_sources(source_id,title,url,publisher,source_kind,retrieved_at,license_id,evidence) VALUES(?,?,?,?,?,?,?,?)',
                      ('isolated-source','Test source','https://example.invalid/product','Test manufacturer','test','2026-10-07','facts_only','Test reference fixture'))
            c.execute('UPDATE account_provenance SET source_id=?,identity_status=?,note=? WHERE user_id=?',
                      ('isolated-source','unassigned_anonymized_profile','Test profile, no confirmed grade',worker['id']))
            mid=c.execute('INSERT INTO materials(code,name,unit,unit_price) VALUES(?,?,?,0)',('REF-TEST','Справочная смазка','кг')).lastrowid
            c.execute('INSERT INTO material_reference_metadata(material_id,source_id,manufacturer,model,note) VALUES(?,?,?,?,?)',
                      (mid,'isolated-source','Test manufacturer','Test model','Reference only, no actual price'))
        self.assertFalse(store.catalogs(admin)['materials'][0]['unit_price_known'])
        self.assertFalse(next(u for u in store.users(admin) if u['id']==worker['id'])['grade_confirmed'])
        with store.transaction() as c:
            with self.assertRaises(ValueError):store._materials(c,[{'material_id':mid,'quantity':1,'unit':'кг'}])
        # An explicit zero may be legitimate, unlike the unknown-price sentinel.
        store.catalog_upsert(admin,'materials',{'code':'REF-TEST','name':'Справочная смазка','unit':'кг','unit_price':0},mid)
        store.set_employee_profile(admin,worker['id'],'Электрослесарь',3)
        self.assertTrue(store.catalogs(admin)['materials'][0]['unit_price_known'])
        self.assertTrue(next(u for u in store.users(admin) if u['id']==worker['id'])['grade_confirmed'])
        with store.transaction() as c:
            self.assertEqual(store._materials(c,[{'material_id':mid,'quantity':1,'unit':'кг'}])[0]['price'],0)

    def test_production_api_rejects_demo_import_before_reading_archive(self):
        from fastapi.testclient import TestClient
        from server.api import create_app
        from unittest.mock import patch
        app=create_app(Settings(data_dir=self.directory,ai_enabled=False))
        administrator(app.state.store)
        with TestClient(app) as client:
            health=client.get('/health').json()
            self.assertFalse(health['seed_demo'])
            login=client.post('/api/login',json={'username':'isolated.admin','password':'Isolated-only-2026!','role':'admin'})
            self.assertEqual(login.status_code,200,login.text)
            with patch('server.demo_import.merge') as merge:
                response=client.post('/api/admin/import-demo',headers={'Authorization':'Bearer '+login.json()['token']},json={})
                self.assertEqual(response.status_code,403,response.text)
                merge.assert_not_called()
            with app.state.store.transaction() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_direct_demo_merge_also_requires_opt_in(self):
        from server.demo_import import merge
        store=Store(self.directory)
        admin=administrator(store)
        class Control:
            def admin(self,user):self.called=True
        with self.assertRaises(PermissionError):merge(store,admin,Control())


if __name__=='__main__':unittest.main(verbosity=2)
