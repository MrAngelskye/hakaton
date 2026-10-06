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
from app.desktop_notifications import configure_windows_notifications


def main():
    parser=argparse.ArgumentParser(description='НарядAI — локальный или сетевой клиент')
    parser.add_argument('--data-dir',type=Path,help='Папка локальной базы и фото')
    parser.add_argument('--server',help='Адрес общего сервера, например http://192.168.1.10:8000')
    parser.add_argument('--demo',action='store_true',help='Создать учебные аккаунты и справочники только для демонстрации')
    args=parser.parse_args()
    configure_windows_notifications()
    app=QApplication(sys.argv[:1]);app.setApplicationName('NaryadAI');app.setOrganizationName('NaryadAI')
    app.setStyle('Fusion');app.setFont(QFont('Segoe UI',10));apply_theme(app)
    app.setWindowIcon(QIcon(str(ROOT/'assets/branding/km-mark-blue.svg')))
    app.setQuitOnLastWindowClosed(False)
    data=args.data_dir or Path(os.environ.get('NARYADAI_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    try:
        if args.server:
            from app.remote import RemoteStore
            store=RemoteStore(args.server)
        else:store=Store(data,seed_demo=args.demo)
    except Exception as e:
        QMessageBox.critical(None,'Не удалось открыть данные',str(e));return 1
    data.mkdir(parents=True,exist_ok=True);preferences().configure(data/'ui.ini')
    windows={}
    def login_screen():
        if windows.get('main'):
            windows['main'].desktop_notifications.shutdown()
            from app.drafts import clear_user_drafts
            draft_error=False
            try:clear_user_drafts(store,windows['main'].user)
            except OSError:draft_error=True
            if hasattr(store,'logout'):
                try:store.logout()
                except OSError:draft_error=True
            windows['main'].refresh_timer.stop();windows['main'].hide();windows['main'].deleteLater();windows['main']=None
            if draft_error:QMessageBox.warning(None,'Локальные данные','Сессия закрыта, но не все черновики или временные фото удалось удалить. Проверьте доступ к папке данных приложения.')
        login=LoginWindow(store);windows['login']=login;login.logged_in.connect(open_main);login.show()
    def open_main(user):
        window=MainWindow(store,user);windows['main']=window;window.logged_out.connect(login_screen);window.show()
        windows['login'].hide();windows['login'].deleteLater();windows['login']=None
    # Окно входа закрывает приложение; рабочее окно остаётся в трее для уведомлений.
    def event_filter_close(cls):
        def close_event(self,event):
            event.accept();app.quit()
        cls.closeEvent=close_event
    event_filter_close(LoginWindow)
    app.aboutToQuit.connect(lambda:windows['main'].desktop_notifications.shutdown() if windows.get('main') else None)
    login_screen();return app.exec()

if __name__=='__main__':sys.exit(main())
