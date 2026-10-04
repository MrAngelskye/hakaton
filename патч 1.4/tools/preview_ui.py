"""Render local demo screens; no credentials, production DB, or server required."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QBuffer,QIODevice
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.store import Store
from app.theme import apply_theme
from app.motion import preferences
from app.windows import MainWindow,LoginWindow
from app.dialogs import CreateTask


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setStyle('Fusion')
    # Windows offscreen Qt doesn't enumerate system fonts automatically.
    for font in ('segoeui.ttf','segoeuib.ttf'):
        path=Path('C:/Windows/Fonts')/font
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Segoe UI',10));apply_theme(app)
    preferences().set_reduced(True)
    with tempfile.TemporaryDirectory() as temp:
        store=Store(temp);windows=[]
        def save(w,name):
            windows.append(w);w.show();app.processEvents()
            w.grab().save(str(args.output_dir/(name+'.png')))
        login=LoginWindow(store);save(login,'login');login.hide()
        master=store.authenticate('master','1234','master')
        win=MainWindow(store,master);save(win,'master-overview')
        win.navigate('tasks');app.processEvents();win.grab().save(str(args.output_dir/'master-tasks.png'))
        win.navigate('team_schedule');app.processEvents();win.grab().save(str(args.output_dir/'team-schedule.png'))
        dialog=CreateTask(store,master,win);save(dialog,'create-task');dialog.reject()
        win.hide()
        worker=MainWindow(store,store.authenticate('worker1','1234','worker'));save(worker,'worker-overview')
        worker.navigate('tasks');app.processEvents();worker.grab().save(str(args.output_dir/'worker-tasks.png'))
        worker.navigate('schedule');app.processEvents();worker.grab().save(str(args.output_dir/'worker-schedule.png'));worker.hide()
        admin=MainWindow(store,store.authenticate('admin','1234','admin'));admin.resize(1040,760);save(admin,'admin-small')
        admin.navigate('references');app.processEvents();admin.grab().save(str(args.output_dir/'admin-references.png'));admin.hide()
        win.show();win.navigate('overview');app.processEvents()
        preferences().set_reduced(False)
        from io import BytesIO
        from PIL import Image
        frames=[]
        def frame():
            buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);win.grab().save(buffer,'PNG')
            img=Image.open(BytesIO(bytes(buffer.data()))).convert('RGB');img.thumbnail((1020,675));frames.append(img)
        frame();win.navigate('tasks');app.processEvents()
        for _ in range(10):frame();QTest.qWait(25)
        frames[0].save(args.output_dir/'navigation.gif',save_all=True,append_images=frames[1:],duration=[600]+[25]*9+[900],loop=0)
        for w in windows:
            if isinstance(w,MainWindow):w.refresh_timer.stop()
            w.close();w.deleteLater()
        app.processEvents()
    print('Saved UI previews to',args.output_dir)


if __name__=='__main__':main()
