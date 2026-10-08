import sqlite3
import unittest

from app.migrations import DB
from app.roles_migration import ensure_supported_roles
from app.store import LegacyStore


class RoleRetirementTests(unittest.TestCase):
    def test_legacy_account_and_history_survive_but_sessions_and_access_are_revoked(self):
        with sqlite3.connect(':memory:') as connection:
            connection.row_factory=sqlite3.Row
            connection.executescript('''
                PRAGMA foreign_keys=ON;
                CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,description TEXT,applied_at TEXT);
                CREATE TABLE users(id INTEGER PRIMARY KEY,role TEXT,active INTEGER);
                CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id));
                CREATE TABLE history(id INTEGER PRIMARY KEY,actor_id INTEGER REFERENCES users(id));
                INSERT INTO users VALUES(1,'master',1),(2,'manager',1);
                INSERT INTO sessions VALUES('legacy-token',2);
                INSERT INTO history VALUES(1,2);
            ''')
            db=DB(connection,False)
            ensure_supported_roles(db);ensure_supported_roles(db)
            self.assertEqual(connection.execute('SELECT active FROM users WHERE id=2').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT actor_id FROM history').fetchone()[0],2)
            self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations WHERE version='005'").fetchone()[0],1)
            self.assertFalse(connection.execute('PRAGMA foreign_key_check').fetchall())
            with self.assertRaises(PermissionError):LegacyStore.require(connection,{'id':2,'role':'admin'})
            with self.assertRaises(sqlite3.IntegrityError):connection.execute('UPDATE users SET active=1 WHERE id=2')
            with self.assertRaises(sqlite3.IntegrityError):connection.execute("INSERT INTO users VALUES(3,'manager',1)")
            self.assertEqual(LegacyStore.require(connection,{'id':1})['role'],'master')


if __name__=='__main__':unittest.main()
