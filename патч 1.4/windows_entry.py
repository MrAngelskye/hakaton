"""One bundled runtime for the desktop app and the local AI worker."""
import sys
from pathlib import Path


def enable_worker_console():
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return
    import ctypes
    import io
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    if not kernel.AttachConsole(-1):
        kernel.AllocConsole()
    kernel.SetConsoleTitleW('НарядAI — обработчик ИИ')
    kernel.SetConsoleOutputCP(65001)
    kernel.SetConsoleCP(65001)
    # A windowed PyInstaller program initially has no standard streams.
    sys.stdout = io.TextIOWrapper(open('CONOUT$', 'wb', buffering=0), encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(open('CONOUT$', 'wb', buffering=0), encoding='utf-8', line_buffering=True)
    sys.stdin = open('CONIN$', 'r', encoding='utf-8')


if __name__ == '__main__':
    is_worker = Path(sys.executable).stem.lower().endswith('-ai') or '--ai-worker' in sys.argv
    if '--ai-worker' in sys.argv:
        sys.argv.remove('--ai-worker')
    if is_worker:
        enable_worker_console()
        from worker_entry import main
    else:
        from desktop_entry import main
    try:
        raise SystemExit(main())
    except Exception as error:
        import traceback
        if '--smoke-test' in sys.argv:
            import json
            report = Path(sys.argv[sys.argv.index('--smoke-test') + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({'ok': False, 'error': traceback.format_exc()}, ensure_ascii=False), encoding='utf-8')
            raise SystemExit(1)
        from app.packaged import configuration_dir
        from PySide6.QtWidgets import QApplication, QMessageBox
        folder = configuration_dir().parent
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / ('worker-error.log' if is_worker else 'startup-error.log')
        log.write_text(traceback.format_exc(), encoding='utf-8')
        app = QApplication.instance() or QApplication([])
        detail = str(error) if isinstance(error, (ValueError, OSError, PermissionError)) else 'Не удалось запустить программу.'
        QMessageBox.critical(None, 'НарядAI', f'{detail}\nПодробности: {log}')
        raise SystemExit(1)
