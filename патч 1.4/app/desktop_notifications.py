"""Qt native Windows notifications and a tray lifecycle, scoped to the signed-in user."""
import hashlib
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from app.notification_content import notification_content


def configure_windows_notifications():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('NaryadAI.Desktop')
        except (AttributeError, OSError):
            pass


class DesktopNotifications(QObject):
    activated = Signal(object)
    delivered = Signal(str)

    def __init__(self, window, store, user, settings=None):
        super().__init__(window)
        self.window = window
        identity = str(getattr(store, 'url', getattr(store, 'path', 'local'))) + ':' + str(user['id'])
        self.settings = settings or QSettings()
        self.key = 'notifications/' + hashlib.sha256(identity.encode()).hexdigest()[:24]
        try:
            self.seen = [int(i) for i in json.loads(self.settings.value(self.key + '/seen', '[]'))][-2000:]
        except (ValueError, TypeError):
            self.seen = []
        self.pending = []
        self.current_task = None
        self.closed = False
        self.native = QSystemTrayIcon.isSystemTrayAvailable()
        icon = QIcon(str(Path(__file__).resolve().parents[1] / 'web/icons/icon-192.png'))
        if icon.isNull():
            icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('НарядAI · ' + user['name'])
        self.menu = QMenu(window)
        self.menu.addAction('Открыть НарядAI', self.restore)
        self.menu.addAction('Уведомления', lambda: self.open(None))
        self.enabled_action = self.menu.addAction('Показывать уведомления')
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(self.enabled)
        self.enabled_action.toggled.connect(self.set_enabled)
        self.menu.addAction('Проверить уведомление', self.test)
        self.menu.addSeparator()
        self.menu.addAction('Завершить приложение', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.messageClicked.connect(lambda: self.open(self.current_task))
        self.tray.activated.connect(self.tray_activated)
        self.timer = QTimer(self)
        self.timer.setInterval(7000)
        self.timer.timeout.connect(self.show_next)
        if self.native:
            self.tray.show()

    @property
    def enabled(self):
        return self.settings.value(self.key + '/enabled', True, type=bool)

    def set_enabled(self, enabled):
        self.settings.setValue(self.key + '/enabled', bool(enabled))
        self.enabled_action.setChecked(bool(enabled))
        if not enabled:
            self.pending.clear()
            self.timer.stop()

    def feed(self, items):
        if self.closed or not self.enabled:
            return
        unread = {item['id'] for item in items if not item.get('read_at')}
        # A read/acknowledged message must not pop up later from the local queue.
        self.pending = [entry for entry in self.pending if any(nid in unread for nid in entry['ids'])]
        queued = {nid for entry in self.pending for nid in entry['ids']}
        fresh = [item for item in items if item['id'] in unread and item['id'] not in self.seen and item['id'] not in queued]
        fresh.sort(key=lambda item: (notification_content(item)['severity'] != 'critical', -item['id']))
        # Do not flood Windows with an entire backlog after reconnecting.
        if len(fresh) > 5:
            critical = next((item for item in fresh if notification_content(item)['severity'] == 'critical'), None)
            if critical:
                self.pending.append({**critical, **notification_content(critical), 'ids': [critical['id']]})
                fresh.remove(critical)
            self.pending.append({'ids': [item['id'] for item in fresh], 'task_id': None,
                                 'title': f'Новых уведомлений: {len(fresh)}',
                                 'body': 'Откройте центр уведомлений, чтобы увидеть назначения и сообщения.', 'severity': 'info'})
        else:
            self.pending.extend({**item, **notification_content(item), 'ids': [item['id']]} for item in fresh)
        if self.pending and not self.timer.isActive():
            # Defer until MainWindow has connected signals and finished its first render.
            self.timer.start()
            QTimer.singleShot(0, self, self.show_next)

    def show_next(self):
        if self.closed or not self.enabled or not self.pending:
            self.timer.stop()
            return
        item = self.pending.pop(0)
        self.show(item['title'], item['body'], item['severity'], item.get('task_id'))
        self.seen = list(dict.fromkeys(self.seen + item['ids']))[-2000:]
        self.settings.setValue(self.key + '/seen', json.dumps(self.seen))
        self.settings.sync()
        if not self.pending:
            self.timer.stop()

    def show(self, title, body, severity='info', task_id=None):
        self.current_task = task_id
        if self.native and QSystemTrayIcon.supportsMessages():
            icon = QSystemTrayIcon.MessageIcon.Warning if severity in ('critical', 'warning') else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage('НарядAI · ' + title, body[:500], icon, 10000)
        self.delivered.emit(title + (' · ' + body.replace('\n', ' ') if body else ''))

    def test(self):
        self.show('Уведомления подключены', 'Срочные наряды, сроки и сообщения будут появляться здесь.')

    def restore(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def open(self, task_id):
        if self.closed:
            return
        self.restore()
        self.activated.emit(task_id)

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore()

    def hide_to_tray(self):
        if not self.native or self.closed:
            return False
        self.window.hide()
        if not self.settings.value(self.key + '/tray_hint', False, type=bool):
            self.show('Приложение работает в фоне', 'Полный выход: значок НарядAI возле часов → Завершить приложение. Уведомления настраиваются в меню значка.')
            self.settings.setValue(self.key + '/tray_hint', True)
        return True

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self.pending.clear()
        self.tray.hide()

    def quit(self):
        self.shutdown()
        QApplication.instance().quit()
