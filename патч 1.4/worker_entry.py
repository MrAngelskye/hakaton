"""Console EXE for the local AI worker, with a graphical settings picker."""
import argparse
import logging
import sys
from pathlib import Path

from app.packaged import read_object, save_object, worker_config_paths


def choose_settings():
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    app = QApplication.instance() or QApplication([])
    QMessageBox.information(None, 'НарядAI — обработчик ИИ',
                            'Выберите папку прежнего проекта, где находятся ваши '
                            'worker_config.json и server_config.json. '
                            'Файлы с ключами останутся только на этом компьютере.')
    folder = QFileDialog.getExistingDirectory(None, 'Папка настроек AnythingLLM')
    if not folder:
        return None
    worker, server = Path(folder) / 'worker_config.json', Path(folder) / 'server_config.json'
    if not worker.is_file() or not server.is_file():
        raise ValueError('В выбранной папке нужны worker_config.json и server_config.json из работающего проекта.')
    return worker, server


def load_worker(worker_path, server_path):
    from server.config import Settings
    from server.anythingllm import AnythingLLM
    from worker import Worker
    data = read_object(worker_path)
    if not isinstance(data.get('server'), str) or not isinstance(data.get('token'), str):
        raise ValueError('В worker_config.json нужны server и token.')
    settings = Settings.load(server_path)
    if not settings.api_key:
        raise ValueError('В server_config.json нужен API-ключ AnythingLLM.')
    return Worker(data['server'], data['token'], AnythingLLM(settings))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--change-settings', action='store_true')
    parser.add_argument('--worker-config', type=Path)
    parser.add_argument('--server-config', type=Path)
    parser.add_argument('--smoke-test', type=Path)
    args = parser.parse_args()
    if args.smoke_test:
        from tools.packaged_smoke import worker_smoke
        return worker_smoke(args.smoke_test)
    if bool(args.worker_config) != bool(args.server_config):
        raise ValueError('Укажите оба файла настроек.')
    paths = (args.worker_config, args.server_config) if args.worker_config else None
    if paths is None and not args.change_settings:
        paths = worker_config_paths()
    if paths is None:
        paths = choose_settings()
    if paths is None:
        return 0
    worker = load_worker(*paths)
    save_object('ai_paths.json', {'worker': str(paths[0].resolve()), 'server': str(paths[1].resolve())})
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    print('НарядAI — обработчик ИИ', flush=True)
    print('Сервер: ' + worker.server, flush=True)
    print('Откройте Ollama и AnythingLLM. Ожидаю отчёты и сообщения чата…', flush=True)
    print('Это окно оставьте открытым. Остановка: Ctrl+C или закрытие окна.', flush=True)
    worker.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, PermissionError) as error:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 'Обработчик ИИ', str(error))
        raise SystemExit(1)
