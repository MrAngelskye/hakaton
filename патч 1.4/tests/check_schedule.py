"""Проверки пауз, смен, свободных окон и миграции. python tests/check_schedule.py"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile,unittest
from datetime import date,datetime,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QDate,QTime
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QLabel
from app.store import Store,SITES
from app.widgets import ROOT
from app.windows import MainWindow
from app.dialogs import PauseTask,CreateTask,EditShift,TaskDetails

APP=QApplication.instance() or QApplication([])
from app.theme import apply_theme
APP.setStyle('Fusion');apply_theme(APP)

class ScheduleChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root,seed_demo=True)
        self.master=self.store.authenticate('master','1234','master');self.admin=self.store.authenticate('admin','1234','admin')
        self.worker=self.store.authenticate('worker4','1234','worker');self.other=self.store.authenticate('worker3','1234','worker')
        self.day=(date.today()+timedelta(days=2)).isoformat();self.windows=[]
    def tearDown(self):
        for w in self.windows:w.close();w.deleteLater()
        APP.processEvents();self.temp.cleanup()
    def show(self,w):
        self.windows.append(w);w.show();APP.processEvents();return w
    def create(self,start=10,duration=1,**kw):
        values=dict(title='Проверка рабочего графика',description='Проверить датчики и выполнить контрольный запуск.',site=SITES[0],equipment='Стенд 1',
                    priority='normal',kind='Плановая',duration=duration,day=self.day,start=start,deadline=self.day+'T20:00',worker_id=self.worker['id'])
        values.update(kw);return self.store.create_task(self.master,**values)
    def at(self,hour):return datetime.fromisoformat(self.day+f'T{hour}:00')
    def test_shift_permissions_bounds_and_slots(self):
        wid=self.worker['id'];self.store.set_shift(self.master,wid,self.day,7.5,16)
        with self.assertRaises(PermissionError):self.store.set_shift(self.worker,wid,self.day,8,18)
        with self.assertRaises(PermissionError):self.store.shift(self.other,wid,self.day)
        with self.assertRaises(ValueError):self.store.set_shift(self.master,wid,self.day,18,8)
        with self.assertRaises(ValueError):self.create(start=7)
        with self.assertRaises(ValueError):self.create(start=15.5,duration=1)
        t1=self.create(start=8);self.create(start=12,duration=2)
        with self.assertRaises(ValueError):self.create(start=8.5)
        self.assertEqual(self.store.free_slots(self.master,wid,self.day),[(7.5,8),(9,12),(14,16)])
        self.assertEqual(self.store.free_slots(self.master,wid,self.day,at=self.at('10')),[(10,12),(14,16)])
        with self.assertRaises(ValueError):self.store.set_shift(self.master,wid,self.day)
        with self.assertRaises(ValueError):self.store.set_shift(self.master,wid,self.day,9,16)
        self.store.reschedule(self.master,t1,self.day,10)
        self.assertEqual(self.store.task(self.worker,t1)['start'],10)
        off=(date.fromisoformat(self.day)+timedelta(days=1)).isoformat();self.store.set_shift(self.admin,wid,off)
        self.assertIsNone(self.store.shift(self.master,wid,off));self.assertEqual(self.store.free_slots(self.master,wid,off),[])
        with self.assertRaises(ValueError):self.create(day=off,deadline=off+'T20:00')
    def test_all_employee_colors(self):
        wid=self.worker['id']
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('07')),'off')
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('09')),'free')
        tid=self.create(start=12)
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('09')),'queued')
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('12')),'busy')
        self.store.transition(self.worker,tid,'inProgress');self.store.transition(self.worker,tid,'paused','Ожидаю помощь мастера')
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('14')),'busy')
        self.assertEqual(self.store.free_slots(self.master,wid,self.day,self.at('14')),[])
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('18')),'off')
        self.store.transition(self.master,tid,'cancelled')
        self.assertEqual(self.store.employee_status(self.master,wid,self.at('14')),'free')
    def test_pause_reason_roundtrip_and_migration(self):
        tid=self.create();self.store.transition(self.worker,tid,'inProgress')
        with self.assertRaises(ValueError):self.store.transition(self.worker,tid,'paused',' ')
        with self.assertRaises(PermissionError):self.store.transition(self.other,tid,'paused','Ожидание материалов')
        self.assertEqual(self.store.task(self.worker,tid)['status'],'inProgress')
        self.store.transition(self.worker,tid,'paused','Нет необходимых материалов')
        self.assertEqual(self.store.pauses(self.master,tid)[0]['reason'],'Нет необходимых материалов')
        self.store.transition(self.admin,tid,'inProgress')
        self.assertIsNotNone(self.store.pauses(self.worker,tid)[0]['ended'])
        self.store.transition(self.worker,tid,'paused','Сломался инструмент');self.store.transition(self.master,tid,'cancelled')
        self.assertEqual(len(self.store.pauses(self.master,tid)),2)
        self.assertTrue(all(p['ended'] for p in self.store.pauses(self.master,tid)))
        again=Store(self.root,seed_demo=True);self.assertEqual(len(again.pauses(self.master,tid)),2)
        self.assertTrue(any('Нет необходимых материалов' in e['message'] for e in again.events(self.master,tid)))
        # Восстановить схему 1.1 и проверить переход без удаления исходных данных.
        old=self.create(start=14);self.store.transition(self.worker,old,'inProgress')
        with self.store.transaction() as c:
            c.execute("UPDATE tasks SET status='paused' WHERE id=?",(old,))
            for table in ('pauses','shifts','shift_rules'):c.execute('DROP TABLE '+table)
            before=c.execute('SELECT count(*) FROM reports').fetchone()[0]
        marker=self.store.photos/'kept.txt';marker.write_text('Фото остаются на месте')
        migrated=Store(self.root,seed_demo=True);self.assertEqual(migrated.task(self.worker,old)['status'],'paused')
        self.assertIn('1.1',migrated.pauses(self.master,old)[0]['reason']);self.assertTrue(marker.exists())
        with migrated.transaction() as c:self.assertEqual(c.execute('SELECT count(*) FROM reports').fetchone()[0],before)
        self.assertEqual(len(Store(self.root,seed_demo=True).pauses(self.master,old)),1)
    def test_gui_schedule_assignment_and_pause(self):
        win=self.show(MainWindow(self.store,self.master));win.schedule_day=QDate.fromString(self.day,'yyyy-MM-dd');win.navigate('team_schedule');APP.processEvents()
        self.assertEqual(win.page_key,'team_schedule');self.assertTrue(any('Назначить на это время'==b.text() for b in win.findChildren(QPushButton)))
        win.grab().save(str(self.root/'schedule.png'))
        d=self.show(CreateTask(self.store,self.master,win,assignment=(self.worker['id'],self.day,9,9.5)))
        self.assertEqual(d.duration.value(),.5);self.assertEqual(d.start.time(),QTime(9,0));self.assertEqual(d.worker.currentData(),self.worker['id'])
        d.title.setText('Проверка по свободному окну');d.description.setPlainText('Проверить контакты и записать результаты.');d.save()
        self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
        tid=max(t['id'] for t in self.store.tasks(self.master));self.store.transition(self.worker,tid,'accepted');self.store.transition(self.worker,tid,'inProgress')
        pause=self.show(PauseTask(self.store,self.worker,tid,win));pause.save()
        self.assertNotEqual(pause.result(),QDialog.DialogCode.Accepted)
        pause.reason.setPlainText('Нет сменного датчика на складе');pause.save();self.assertEqual(pause.result(),QDialog.DialogCode.Accepted)
        details=self.show(TaskDetails(self.store,self.master,tid,win));self.assertTrue(any('Нет сменного датчика' in l.text() for l in details.findChildren(QLabel)))
        edit=self.show(EditShift(self.store,self.master,self.worker,self.day,win));edit.start.setTime(QTime(7,0));edit.end.setTime(QTime(19,0));edit.save()
        self.assertEqual(edit.result(),QDialog.DialogCode.Accepted);self.assertEqual(self.store.shift(self.master,self.worker['id'],self.day),{'start':7,'end':19})
        win.navigate('team');self.assertFalse(win.grab().isNull())
        worker_win=self.show(MainWindow(self.store,self.worker));self.assertNotIn('team_schedule',worker_win.nav)
        worker_win.schedule_day=QDate.fromString(self.day,'yyyy-MM-dd');worker_win.navigate('schedule');self.assertFalse(worker_win.grab().isNull())

if __name__=='__main__':unittest.main(verbosity=2)
