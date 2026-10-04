"""Запуск: python tests/check_app.py. Использует отдельную временную базу."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QDate
from PySide6.QtGui import QImage,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
from app.store import Store,SITES
from app.widgets import ROOT
from app.windows import LoginWindow,MainWindow
from app.dialogs import CreateTask,TaskDetails,SubmitReport,ReviewReport,AddUser,SupportTask

APP=QApplication.instance() or QApplication([])
from app.theme import apply_theme
APP.setStyle('Fusion');apply_theme(APP)


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.store=Store(self.folder)
        self.master=self.store.authenticate('master','1234','master');self.worker=self.store.authenticate('worker1','1234','worker')
        self.other=self.store.authenticate('worker2','1234','worker');self.admin=self.store.authenticate('admin','1234','admin')
        self.windows=[]
    def tearDown(self):
        for w in self.windows:w.close();w.deleteLater()
        APP.processEvents();self.temp.cleanup()
    def show(self,w):
        self.windows.append(w);w.show();APP.processEvents();return w
    def create(self,**kwargs):
        values=dict(title='Тест контрольного привода',description='Проверить привод и выполнить контрольный запуск.',site=SITES[0],equipment='Привод П-1',
                    priority='normal',kind='Плановая',duration=1,day=QDate.currentDate().toString('yyyy-MM-dd'),start=13,
                    deadline=QDate.currentDate().toString('yyyy-MM-dd')+'T18:00',worker_id=None)
        values.update(kwargs);return self.store.create_task(self.master,**values)
    def report(self,tid):
        return self.store.submit(self.worker,tid,work='Очищены контакты и подтянуты крепления.',result='Работает штатно',defect='D-03 · Загрязнение',hours=1,
            materials=[dict(name='Салфетки',quantity=2,unit='шт.',price=50)],photo_sources=[])
    def test_permissions_and_schedule(self):
        with self.assertRaises(ValueError):self.store.authenticate('master','bad','master')
        with self.assertRaises(ValueError):self.store.authenticate('master','1234','worker')
        with self.assertRaises(PermissionError):self.store.create_task(self.worker,title='aaaaa',description='0123456789',site=SITES[0],equipment='x',priority='normal',kind='Плановая',duration=1,day='2026-10-03',start=12,deadline='2026-10-03T18:00')
        tid=self.create();day=QDate.currentDate().toString('yyyy-MM-dd')
        with self.assertRaises(ValueError):self.store.claim(self.worker,tid,day,8)
        self.store.claim(self.worker,tid,day,13)
        with self.assertRaises(ValueError):self.store.claim(self.other,tid,day,13)
        with self.assertRaises(PermissionError):self.store.task(self.other,tid)
        with self.assertRaises(PermissionError):self.store.transition(self.other,tid,'inProgress')
        self.store.transition(self.worker,tid,'inProgress');self.store.transition(self.worker,tid,'paused','Ожидание материалов');self.store.transition(self.worker,tid,'inProgress')
        rid=self.report(tid)
        with self.assertRaises(PermissionError):self.store.review(self.worker,rid,True,90,'Нельзя')
        with self.assertRaises(ValueError):self.store.review(self.master,rid,True,101,'Оценка')
        self.store.review(self.master,rid,False,None,'Уточните результат проверки')
        self.assertEqual(self.store.task(self.worker,tid)['status'],'revision')
        rid2=self.report(tid);self.assertNotEqual(rid,rid2)
        self.assertEqual(next(r for r in self.store.reports(self.worker) if r['id']==rid)['status'],'superseded')
        self.store.review(self.master,rid2,True,87,'Контрольная проверка описана')
        with self.assertRaises(ValueError):self.store.review(self.master,rid2,True,90,'Повтор')
        self.assertEqual(self.store.task(self.worker,tid)['status'],'approved')
        self.assertEqual(len([r for r in self.store.reports(self.worker) if r['task_id']==tid]),2)
        self.assertTrue(any('Возврат' in e['message'] for e in self.store.events(self.worker,tid)))
        metrics=next(p for p in self.store.metrics(self.master) if p['id']==self.worker['id'])
        self.assertEqual(metrics['done'],3);self.assertAlmostEqual(metrics['score'],(94+91+87)/3)
        again=Store(self.folder);self.assertEqual(again.task(self.worker,tid)['status'],'approved')
        export=self.folder/'reports.csv';again.export_reports(self.master,export)
        with export.open(encoding='utf-8-sig') as f:rows=list(csv.reader(f,delimiter=';'))
        self.assertTrue(any(row[1]==str(tid) and row[6]=='87' and row[7]=='100' for row in rows[1:]))
    def test_existing_site_survives_update_and_support_edit(self):
        with self.store.transaction() as c:
            c.execute("UPDATE tasks SET site='Сборочный цех' WHERE id=1048")
        again=Store(self.folder)
        task=again.task(self.admin,1048)
        self.assertEqual(task['site'],'Сборочный цех')
        dialog=self.show(SupportTask(again,self.admin,task,None))
        self.assertEqual(dialog.site.currentData(),'Сборочный цех')
        values={key:task[key] for key in ('title','description','site','equipment','priority','kind','duration','day','start','deadline','worker_id')}
        values.update(description=task['description']+' Уточнение.',reason='Уточнить описание')
        again.support_update_task(self.admin,1048,**values)
        self.assertEqual(again.task(self.admin,1048)['site'],'Сборочный цех')
        values.update(site='Произвольный неизвестный участок')
        with self.assertRaises(ValueError):again.support_update_task(self.admin,1048,**values)

    def test_admin_and_photos(self):
        self.store.add_user(self.admin,'new','Тестовый Сотрудник','Механик','worker','4321')
        new=self.store.authenticate('new','4321','worker');self.store.set_active(self.admin,new['id'],False)
        with self.assertRaises(ValueError):self.store.authenticate('new','4321','worker')
        with self.assertRaises(PermissionError):self.store.tasks(new)
        with self.assertRaises(ValueError):self.store.set_active(self.admin,self.worker['id'],False)
        tid=self.create(worker_id=self.worker['id']);self.store.transition(self.worker,tid,'inProgress')
        image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor('#4b50dc'));path=self.folder/'before.png';image.save(str(path))
        rid=self.store.submit(self.worker,tid,work='Проведён контрольный запуск оборудования',result='Замечаний нет',defect='Нет',hours=1,materials=[],photo_sources=[str(path)])
        path.unlink();report=self.store.latest_report(self.worker,tid);self.assertEqual(rid,report['id'])
        self.assertTrue((self.store.photos/report['photos'][0]).exists())
    def test_gui_all_pages(self):
        login=self.show(LoginWindow(self.store));found=[];login.logged_in.connect(found.append)
        login.choose_role('master');QTest.mouseClick(login.enter,Qt.MouseButton.LeftButton);APP.processEvents();self.assertEqual(found[0]['role'],'master')
        for user,pages in [(self.master,['overview','tasks','reports','team','costs']),
                           (self.worker,['tasks','schedule','reports','profile']),
                           (self.admin,['overview','tasks','reports','team','costs','users','integrations'])]:
            win=self.show(MainWindow(self.store,user))
            for page in pages:
                QTest.mouseClick(win.nav[page],Qt.MouseButton.LeftButton);APP.processEvents();self.assertEqual(win.page_key,page)
                self.assertFalse(win.grab().isNull())
                if page=='tasks':
                    win.search.setText('does not exist');QTest.qWait(220);self.assertEqual(win.query,'does not exist')
                    win.search.clear();QTest.qWait(220)
            win.hide()
    def test_gui_full_workflow(self):
        parent=self.show(MainWindow(self.store,self.master));d=self.show(CreateTask(self.store,self.master,parent))
        d.title.setText('Проверка нового привода');d.description.setPlainText('Проверить контакты и выполнить контрольный запуск.');d.equipment.setText('Привод П-3');d.save()
        self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
        tid=max(t['id'] for t in self.store.tasks(self.master));day=QDate.currentDate().toString('yyyy-MM-dd');self.store.claim(self.worker,tid,day,13)
        self.store.transition(self.worker,tid,'inProgress')
        submit=self.show(SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),parent))
        submit.work.setPlainText('Проверены контакты и выполнен контрольный запуск.');submit.result_text.setPlainText('Оборудование исправно');submit.add_material({'name':'Смазка','quantity':.2,'unit':'кг','price':1000});submit.save()
        self.assertEqual(submit.result(),QDialog.DialogCode.Accepted)
        r=self.store.latest_report(self.master,tid);review=self.show(ReviewReport(self.store,self.master,r,parent))
        review.comment.setPlainText('Добавить сведения о нагрузке');review.decide(False);self.assertEqual(review.result(),QDialog.DialogCode.Accepted)
        again=self.show(SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),parent))
        self.assertEqual(again.work.toPlainText(),r['work']);self.assertEqual(again.table.rowCount(),1)
        again.result_text.setPlainText('Контрольный запуск при нагрузке 50% выполнен без замечаний');again.save()
        review2=self.show(ReviewReport(self.store,self.master,self.store.latest_report(self.master,tid),parent))
        review2.score.setValue(93);review2.comment.setPlainText('Работа принята, замечаний нет');review2.decide(True)
        self.assertEqual(self.store.task(self.worker,tid)['status'],'approved')
        self.show(TaskDetails(self.store,self.master,tid,parent))
        add=self.show(AddUser(self.store,self.admin,parent));add.username.setText('guiuser');add.name.setText('Новый Пользователь');add.password.setText('5555');add.save()
        self.assertEqual(add.result(),QDialog.DialogCode.Accepted)

if __name__=='__main__':unittest.main(verbosity=2)
