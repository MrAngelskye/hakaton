"""Windows entry point: GUI connection screen, then the existing application."""
import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QHBoxLayout

from app.packaged import client_server, configuration_dir, save_object
from app.remote import RemoteStore
from app.theme import apply_theme
from app.widgets import ROOT
from tools.client_launcher import normalize_url


class ConnectionThread(QThread):
    status = Signal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url, self.store, self.error = url, None, ''

    def run(self):
        deadline = time.monotonic() + 100
        while not self.isInterruptionRequested():
            try:
                self.store = RemoteStore(self.url)
                return
            except OSError as error:
                self.error = str(error)
                if time.monotonic() >= deadline:
                    return
                self.status.emit('Сервер запускается. Это может занять около минуты…')
                for _ in range(20):
                    if self.isInterruptionRequested():
                        return
                    self.msleep(100)
            except (ValueError, PermissionError) as error:
                self.error = str(error)
                return


class ConnectionDialog(QDialog):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle('НарядAI — подключение')
        self.setMinimumWidth(460)
        self.store, self.thread, self.cancelled = None, None, False
        layout = QVBoxLayout(self)
        title = QLabel('Подключение к общей базе НарядAI')
        title.setFont(QFont('Segoe UI', 14))
        layout.addWidget(title)
        self.address = QLineEdit(url)
        self.address.setPlaceholderText('https://адрес-сервера.onrender.com')
        layout.addWidget(self.address)
        self.status = QLabel('Задачи, отчёты и чат доступны обоим участникам через сервер.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.connect_button = QPushButton('Подключиться')
        self.connect_button.clicked.connect(self.connect_server)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def connect_server(self):
        try:
            url = normalize_url(self.address.text())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.address.setText(url)
        self.address.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.status.setText('Подключаюсь к серверу…')
        self.thread = ConnectionThread(url, self)
        self.thread.status.connect(self.status.setText)
        self.thread.finished.connect(self.connection_finished)
        self.thread.start()

    def connection_finished(self):
        if self.cancelled:
            super().reject()
        elif self.thread.store is not None:
            try:
                save_object('client_config.json', {'server': self.thread.url})
            except OSError:
                self.status.setText('Не удалось сохранить адрес. Проверьте доступ к папке настроек.')
                self.address.setEnabled(True)
                self.connect_button.setEnabled(True)
                return
            self.store = self.thread.store
            self.accept()
        else:
            self.status.setText(self.thread.error or 'Не удалось подключиться к серверу.')
            self.address.setEnabled(True)
            self.connect_button.setEnabled(True)

    def reject(self):
        if self.thread is not None and self.thread.isRunning():
            self.cancelled = True
            self.thread.requestInterruption()
            self.status.setText('Завершаю подключение…')
            self.connect_button.setEnabled(False)
        else:
            super().reject()

    def closeEvent(self, event):
        self.reject()
        if self.thread is not None and self.thread.isRunning():
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--change-server', action='store_true')
    parser.add_argument('--smoke-test', type=Path)
    args = parser.parse_args()
    if args.smoke_test:
        from tools.packaged_smoke import desktop_smoke
        return desktop_smoke(args.smoke_test)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('NaryadAI')
    app.setOrganizationName('NaryadAI')
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI', 10))
    apply_theme(app)
    app.setWindowIcon(QIcon(str(ROOT / 'assets/branding/km-mark-blue.svg')))
    try:
        url = client_server()
    except (ValueError, OSError) as error:
        QMessageBox.warning(None, 'Настройки подключения', str(error))
        from app.packaged import DEFAULT_SERVER
        url = DEFAULT_SERVER
        args.change_server = True
    dialog = ConnectionDialog(url)
    if not args.change_server:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, dialog.connect_server)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0
    from main import main as application_main
    return application_main(['--server', dialog.address.text()], store_override=dialog.store)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        folder = configuration_dir().parent
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / 'startup-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 'НарядAI', f'Не удалось запустить приложение. Подробности: {log}')
        raise SystemExit(1)
