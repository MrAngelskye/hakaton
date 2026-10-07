"""Offline checks executed by the actual frozen Windows programs in CI."""
import json
import tempfile
from pathlib import Path


def desktop_smoke(output):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from app.store import Store
    from app.windows import LoginWindow, MainWindow
    from app.theme import apply_theme
    from app.widgets import ROOT
    from app.speech import default_model_path, native_model_path, valid_model_path
    from app.desktop_notifications import configure_windows_notifications
    import sounddevice
    from vosk import Model, SetLogLevel
    configure_windows_notifications()
    app = QApplication([])
    app.setApplicationName('NaryadAI-Smoke')
    apply_theme(app)
    icon = QIcon(str(ROOT / 'assets/branding/km-mark-blue.svg'))
    assert not icon.pixmap(64, 64).isNull(), 'SVG plugin or branding missing'
    assert (ROOT / 'web/icons/icon-192.png').is_file(), 'Notification icon missing'
    model_path = default_model_path()
    assert valid_model_path(model_path), 'Dictation model missing'
    SetLogLevel(-1)
    model = Model(native_model_path(model_path))
    windows = []
    with tempfile.TemporaryDirectory() as folder:
        store = Store(folder, seed_demo=True)
        login = LoginWindow(store)
        login.show()
        app.processEvents()
        login.close()
        for username, role in (('admin', 'admin'), ('master', 'master'), ('worker1', 'worker')):
            user = store.authenticate(username, '1234', role)
            assert user is not None, role
            window = MainWindow(store, user)
            window.show()
            app.processEvents()
            window.refresh_timer.stop()
            window.desktop_notifications.shutdown()
            window.hide()
            window.deleteLater()
            windows.append(role)
            QCoreApplication.sendPostedEvents()
    del model
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'ok': True, 'roles': windows, 'voice': True, 'svg': True}, indent=2), encoding='utf-8')
    return 0


def worker_smoke(output):
    from worker_entry import load_worker
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        worker_path, server_path = root / 'worker_config.json', root / 'server_config.json'
        worker_path.write_text(json.dumps({'server': 'https://example.com', 'token': 'x' * 32}), encoding='utf-8')
        server_path.write_text(json.dumps({'base_url': 'http://127.0.0.1:3001', 'api_key': 'smoke-only', 'workspace': 'naryadai'}), encoding='utf-8')
        worker = load_worker(worker_path, server_path)
        assert worker.ai.settings.workspace == 'naryadai'
        assert worker.server == 'https://example.com'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'ok': True, 'worker': True, 'network_requests': 0}, indent=2), encoding='utf-8')
    return 0
