"""Qt smoke checks for catalog fields, new statuses and overnight shift inputs."""
import os,sys,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QWidget
from app.store import Store
from app.dialogs import CreateTask,SubmitReport,TaskDetails,EditShift
from app.windows import LoginWindow,MainWindow
from datetime import date,timedelta

class UISmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name,seed_demo=True);self.master=self.store.authenticate('master','1234','master');self.worker=self.store.authenticate('worker1','1234','worker');self.parent=QWidget()
    def tearDown(self):self.parent.close();self.temp.cleanup()
    def test_catalog_widgets_and_material_price(self):
        d=CreateTask(self.store,self.master,self.parent)
        self.assertEqual(d.priority.count(),4);self.assertGreater(d.equipment.count(),0)
        d.site.setCurrentIndex(1);self.assertGreater(d.equipment.count(),0)
        e=next(x for x in self.store.catalogs(self.master)['equipment'] if x['id']==d.equipment.currentData());self.assertEqual(e['site_id'],self.store.catalogs(self.master)['sites'][1]['id'])
        day=(date.today()+timedelta(days=10)).isoformat();tid=self.store.create_task(self.master,title='Ремонт агрегата',description='Проверить состояние и контрольный запуск',site=d.site.currentData(),equipment=d.equipment.currentText(),equipment_id=e['id'],priority='high',kind='Внеплановая',duration=1,day=day,start=8,deadline=day+'T18:00',worker_id=self.worker['id'])
        details=TaskDetails(self.store,self.worker,tid,self.parent);self.assertTrue(any('Принять' in widget.text() for widget in details.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)))
        report=SubmitReport(self.store,self.worker,self.store.task(self.worker,tid),self.parent);report.add_material();self.assertIsNotNone(report.table.cellWidget(0,0));self.assertTrue(report.table.item(0,2).text());self.assertGreater(report.defect.count(),4)
        details.close();report.close();d.close()
    def test_login_manager_and_main_pages(self):
        login=LoginWindow(self.store);self.assertEqual(len(login.roles.buttons()),4);login.choose_role('manager');self.assertEqual(login.username.text(),'manager');login.close()
        window=MainWindow(self.store,self.master)
        for page in ('overview','tasks','reports','team','team_schedule','costs','analytics'):window.navigate(page)
        window.close()
    def test_overnight_edit_shift(self):
        day=(date.today()+timedelta(days=10)).isoformat();self.store.set_shift(self.master,self.worker['id'],day,22,6)
        d=EditShift(self.store,self.master,self.worker,day,self.parent);self.assertEqual(d.end.time().hour(),6);d.close()

if __name__=='__main__':unittest.main(verbosity=2)
