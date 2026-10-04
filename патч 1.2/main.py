import argparse
import os
import sys
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication,QMessageBox
from app.store import Store
from app.widgets import ROOT,icon
from app.windows import LoginWindow,MainWindow


def main():
    parser=argparse.ArgumentParser(description='НарядAI — desktop-приложение без ИИ')
    parser.add_argument('--data-dir',type=Path,help='Папка локальной базы и фото')
    args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setApplicationName('NaryadAI');app.setOrganizationName('NaryadAI')
    app.setStyle('Fusion');app.setFont(QFont('Segoe UI',10));app.setStyleSheet((ROOT/'assets'/'styles.qss').read_text(encoding='utf-8'))
    app.setWindowIcon(icon('brand','#4b50dc'))
    app.setQuitOnLastWindowClosed(False)
    data=args.data_dir or Path(os.environ.get('NARYADAI_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    try:store=Store(data)
    except Exception as e:
        QMessageBox.critical(None,'Не удалось открыть данные',str(e));return 1
    windows={}
    def login_screen():
        if windows.get('main'):
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
