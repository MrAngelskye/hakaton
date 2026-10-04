import argparse
import os
import sys
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont,QIcon
from PySide6.QtWidgets import QApplication,QMessageBox
from app.store import Store
from app.widgets import ROOT
from app.windows import LoginWindow,MainWindow
from app.theme import apply_theme
from app.motion import preferences


def main():
    parser=argparse.ArgumentParser(description='НарядAI — локальный или сетевой клиент')
    parser.add_argument('--data-dir',type=Path,help='Папка локальной базы и фото')
    parser.add_argument('--server',help='Адрес общего сервера, например http://192.168.1.10:8000')
    args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setApplicationName('NaryadAI');app.setOrganizationName('NaryadAI')
    app.setStyle('Fusion');app.setFont(QFont('Segoe UI',10));apply_theme(app)
    app.setWindowIcon(QIcon(str(ROOT/'assets/branding/km-mark-blue.svg')))
    app.setQuitOnLastWindowClosed(False)
    data=args.data_dir or Path(os.environ.get('NARYADAI_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    try:
        if args.server:
            from app.remote import RemoteStore
            store=RemoteStore(args.server)
        else:store=Store(data)
    except Exception as e:
        QMessageBox.critical(None,'Не удалось открыть данные',str(e));return 1
    data.mkdir(parents=True,exist_ok=True);preferences().configure(data/'ui.ini')
    windows={}
    def login_screen():
        if windows.get('main'):
            if hasattr(store,'logout'):store.logout()
            windows['main'].refresh_timer.stop();windows['main'].hide();windows['main'].deleteLater();windows['main']=None
        login=LoginWindow(store);windows['login']=login;login.logged_in.connect(open_main);login.show()
    def open_main(user):
        window=MainWindow(store,user);windows['main']=window;window.logged_out.connect(login_screen);window.show()
        windows['login'].hide();windows['login'].deleteLater();windows['login']=None
    # Закрытие крестиком завершает приложение; выход из аккаунта открывает форму входа.
    def event_filter_close(cls):
        def close_event(self,event):
            event.accept();app.quit()
        cls.closeEvent=close_event
    event_filter_close(LoginWindow);event_filter_close(MainWindow)
    login_screen();return app.exec()

if __name__=='__main__':sys.exit(main())
