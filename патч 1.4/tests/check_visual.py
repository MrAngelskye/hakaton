"""Visual interaction regressions: python tests/check_visual.py (no real server)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QEvent,QCoreApplication,QSettings,QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QCheckBox
from PySide6.QtSvg import QSvgRenderer
from app.store import Store
from app.theme import COLORS,apply_theme
from app.motion import preferences,PAGE_DURATION,DIALOG_DURATION
from app.widgets import Sheet,CalendarDialog,motion_toggle
from app.windows import MainWindow,Timeline

APP=QApplication.instance() or QApplication([])
APP.setStyle('Fusion');apply_theme(APP)


def contrast(first,second):
    def luminance(color):
        channels=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        values=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in channels]
        return sum(x*y for x,y in zip(values,(.2126,.7152,.0722)))
    a,b=sorted((luminance(first),luminance(second)))
    return (b+.05)/(a+.05)


class VisualChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.windows=[]
        self.exceptions=[];self.old_hook=sys.excepthook
        sys.excepthook=lambda kind,value,trace:self.exceptions.append(str(value))
        preferences().settings=None;preferences().set_reduced(False)
        self.store=Store(self.temp.name,seed_demo=True);self.master=self.store.authenticate('master','1234','master')
    def tearDown(self):
        for w in self.windows:
            if isinstance(w,MainWindow):w.refresh_timer.stop()
            w.close();w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
        preferences().settings=None;preferences().set_reduced(False);self.temp.cleanup()
        sys.excepthook=self.old_hook;self.assertEqual(self.exceptions,[])
    def show(self,w):
        self.windows.append(w);w.show();APP.processEvents();return w
    def test_text_contrast(self):
        pairs=[('text','surface'),('text','background'),('muted','background'),('muted','surface'),
               ('surface','primary'),('surface','primary_hover'),('surface','primary_pressed'),
               ('sidebar_text','sidebar'),('sidebar_muted','sidebar'),('sidebar_text','sidebar_hover'),
               ('primary_text','primary_soft'),('success','success_soft'),('warning','warning_soft'),
               ('info','info_soft'),('danger','danger_soft'),('purple','purple_soft'),('muted','surface_alt')]
        for fg,bg in pairs:
            with self.subTest(fg=fg,bg=bg):self.assertGreaterEqual(contrast(COLORS[fg],COLORS[bg]),4.5)
    def test_rapid_navigation_keeps_controls_active(self):
        w=self.show(MainWindow(self.store,self.master))
        for key in ('tasks','reports','team','overview','tasks'):
            QTest.mouseClick(w.nav[key],Qt.MouseButton.LeftButton);APP.processEvents()
            self.assertEqual(w.page_key,key)
        self.assertIsNotNone(w.transition.overlay)
        self.assertTrue(w.transition.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        QTest.mouseClick(w.search,Qt.MouseButton.LeftButton);QTest.keyClicks(w.search,'xyz')
        self.assertEqual(w.query,'xyz');self.assertTrue(w.search.hasFocus())
        QTest.qWait(PAGE_DURATION+100)
        self.assertIsNone(w.transition.overlay)
        self.assertNotIn('$primary',APP.styleSheet())
    def test_reduce_motion_stops_effects_and_persists(self):
        path=Path(self.temp.name)/'ui.ini';preferences().configure(path)
        w=self.show(MainWindow(self.store,self.master));w.navigate('reports')
        d=self.show(Sheet('Проверка',w));self.assertIsNotNone(d.reveal.animation)
        toggle=w.findChild(QCheckBox,'motionToggle');toggle.setChecked(True)
        self.assertIsNone(w.transition.overlay);self.assertIsNone(d.reveal.animation)
        self.assertTrue(QSettings(str(path),QSettings.Format.IniFormat).value('accessibility/reduced_motion',type=bool))
        w.navigate('tasks');self.assertIsNone(w.transition.overlay)
        self.assertTrue(motion_toggle().isChecked())
    def test_resize_hide_close_cancel_transitions(self):
        w=self.show(MainWindow(self.store,self.master));w.navigate('reports')
        w.resize(1200,820);APP.processEvents();self.assertIsNone(w.transition.overlay)
        w.navigate('team');w.hide();APP.processEvents();self.assertIsNone(w.transition.overlay)
        d=self.show(CalendarDialog(QDate.currentDate(),w));d.reject()
        self.assertIsNone(d.reveal.animation);self.assertIsNone(d.content.graphicsEffect())
    def test_background_refresh_and_success_feedback(self):
        w=self.show(MainWindow(self.store,self.master))
        w.render(animate=False);self.assertIsNone(w.transition.overlay)
        w.statusBar().showMessage('Нет связи с сервером',5000);self.assertFalse(w.toast.isVisible())
        w.notify_success('Наряд создан');self.assertTrue(w.toast.isVisible())
        self.assertTrue(w.toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        QTest.qWait(DIALOG_DURATION+100);self.assertIsNone(w.toast.graphicsEffect())
    def test_short_timeline_events_do_not_overlap(self):
        tasks=[dict(id=i,start=10+i*.5,duration=.5,status='planned',title='Проверить датчик конвейера') for i in range(2)]
        timeline=self.show(Timeline(tasks,lambda _:None));timeline.resize(700,850);APP.processEvents()
        first,second=[b for _,b in timeline.events]
        self.assertLess(first.geometry().bottom(),second.geometry().top())
        self.assertNotIn('\n',first.text());self.assertIn('Проверить датчик',first.toolTip())
    def test_remote_snapshot_is_quiet(self):
        w=self.show(MainWindow(self.store,self.master));self.store.url='https://demo.invalid';self.store.actor=self.master
        with self.store.transaction() as c:
            c.execute("UPDATE tasks SET description=description || ' Обновлено.'")
        # Exercise the same callback as the network loader, without a real server.
        w.remote_snapshot({'day':w.schedule_day.toString('yyyy-MM-dd')})
        self.assertIsNone(w.transition.overlay);self.assertFalse(w.toast.isVisible())
        self.assertIn('Обновлено.',w.tasks[0]['description'])
    def test_brand_assets_render_without_network(self):
        assets=Path(__file__).resolve().parents[1]/'assets/branding'
        for path in assets.glob('*.svg'):
            with self.subTest(asset=path.name):
                self.assertGreater(path.stat().st_size,0)
                renderer=QSvgRenderer(str(path));self.assertTrue(renderer.isValid())
                self.assertFalse(renderer.defaultSize().isEmpty())


if __name__=='__main__':unittest.main(verbosity=2)
