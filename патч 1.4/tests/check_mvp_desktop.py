"""Desktop report recovery and linked issue flow, on isolated demo data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QDate,QDateTime,QTime
from PySide6.QtGui import QImage,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
from app.store import Store
from app.dialogs import CreateTask,SubmitReport
from app.drafts import ReportDraft
from app.theme import apply_theme

APP=QApplication.instance() or QApplication([])
APP.setStyle('Fusion');apply_theme(APP)


class DesktopMVP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root);self.dialogs=[]
        self.master=self.store.authenticate('master','1234','master');self.worker=self.store.authenticate('worker4','1234','worker')
        self.day=(date.today()+timedelta(days=2)).isoformat()
    def tearDown(self):
        for d in self.dialogs:d.close();d.deleteLater()
        APP.processEvents();self.tmp.cleanup()
    def dialog(self,dialog):
        self.dialogs.append(dialog);return dialog
    def task(self,kind='Плановая'):
        tid=self.store.create_task(self.master,title='Проверить компрессор и привод',description='Проверить соединения и выполнить контрольный запуск.',
            site='Ремонтный участок',equipment='Компрессор КМ-07',priority='high',kind=kind,duration=1,
            day=self.day,start=10,deadline=self.day+'T18:00',worker_id=self.worker['id'],issued=True)
        self.store.transition(self.worker,tid,'accepted');self.store.transition(self.worker,tid,'inProgress');return tid
    def test_linked_issue_and_required_assignment(self):
        d=self.dialog(CreateTask(self.store,self.master,None))
        d.site.setCurrentIndex(d.site.findData('Ремонтный участок'))
        allowed={r['name'] for r in self.store.references(self.master,'equipment','Ремонтный участок')}
        self.assertEqual({d.equipment.itemText(i) for i in range(d.equipment.count())},allowed)
        d.normative.setCurrentIndex(1);self.assertTrue(d.title.text());self.assertTrue(d.description.toPlainText())
        d.day.setDate(QDate.fromString(self.day,'yyyy-MM-dd'));d.start.setTime(QTime(10,0));d.deadline.setDateTime(QDateTime(d.day.date(),QTime(18,0)))
        d.save();self.assertNotEqual(d.result(),QDialog.DialogCode.Accepted)
        d.worker.setCurrentIndex(d.worker.findData(self.worker['id']));d.save()
        self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
        task=self.store.task(self.worker,max(t['id'] for t in self.store.tasks(self.master)))
        self.assertEqual(task['status'],'issued');self.assertIsNotNone(task['normative_id'])
    def test_draft_restores_text_materials_photos_and_clears_on_success(self):
        tid=self.task('Внеплановая');path=self.root/'after.png'
        image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor('#07316E'));image.save(str(path))
        d=self.dialog(SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),None))
        d.work.setPlainText('Проверены соединения, подтянуты крепления.');d.result_text.setPlainText('Контрольный запуск: давление стабильное.')
        d.add_material(dict(name='Смазка',quantity='.2',unit='кг',price='1000'))
        d.photo_sources=[str(path)];d.refresh_photos();QTest.qWait(450)
        self.assertEqual(ReportDraft(self.store,self.worker,tid).load()['photo_sources'],[str(path)])
        d.reject();again=self.dialog(SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),None))
        self.assertEqual(again.work.toPlainText(),d.work.toPlainText());self.assertEqual(again.table.rowCount(),1)
        self.assertEqual(again.photo_sources,[str(path)])
        again.table.selectRow(0);again.remove_material();QTest.qWait(450)
        self.assertEqual(ReportDraft(self.store,self.worker,tid).load()['materials'],[])
        again.save();self.assertEqual(again.result(),QDialog.DialogCode.Accepted)
        self.assertFalse(ReportDraft(self.store,self.worker,tid).path.exists())
        self.assertEqual(self.store.task(self.worker,tid)['status'],'submitted')
    def test_revision_preserves_legacy_defect_and_moves_cached_report_photo(self):
        tid=self.task();path=self.root/'after.png'
        image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor('#001636'));image.save(str(path))
        rid=self.store.submit(self.worker,tid,work='Проверены соединения и проведён контрольный запуск.',result='Давление после запуска стабильно.',
            defect='Старый код: Э-42',hours=1,materials=[],photo_sources=[str(path)])
        self.store.review(self.master,rid,False,None,'Уточнить давление после запуска')
        photo=self.store.latest_report(self.worker,tid)['photos'][0]
        draft=ReportDraft(self.store,self.worker,tid)
        draft.save(dict(work='Дополнить контрольную проверку',result='Давление 6 бар.',defect='Старый код: Э-42',hours=1,
            materials=[],photo_sources=[str(self.root/'previous-cache'/photo)]))
        d=self.dialog(SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),None))
        self.assertEqual(d.defect.currentText(),'Старый код: Э-42')
        self.assertEqual(d.photo_sources,[str(self.store.photos/photo)])


if __name__=='__main__':unittest.main(verbosity=2)
