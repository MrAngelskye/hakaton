"""Configuration kept outside the installed program. Never bundle secrets."""
import json
import os
import sys
from pathlib import Path

DEFAULT_SERVER = 'https://hakaton-cj24.onrender.com'


def configuration_dir():
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / '.config') / 'NaryadAI' / 'config'


def program_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def read_object(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Файл настроек должен содержать JSON-объект.')
    return data


def save_object(name, data):
    folder = configuration_dir()
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / name
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    return destination


def client_server():
    from tools.client_launcher import normalize_url
    if os.environ.get('NARYADAI_SERVER_URL'):
        return normalize_url(os.environ['NARYADAI_SERVER_URL'])
    for path in (configuration_dir() / 'client_config.json', program_dir() / 'client_config.json'):
        if path.is_file():
            value = read_object(path).get('server')
            if not isinstance(value, str) or not value.strip():
                raise ValueError('В client_config.json нужен адрес server.')
            return normalize_url(value)
    return DEFAULT_SERVER


def worker_config_paths():
    pointer = configuration_dir() / 'ai_paths.json'
    if pointer.is_file():
        values = read_object(pointer)
        worker, server = Path(values.get('worker', '')), Path(values.get('server', ''))
        if worker.is_file() and server.is_file():
            return worker, server
    root = program_dir()
    worker, server = root / 'worker_config.json', root / 'server_config.json'
    if worker.is_file() and server.is_file():
        return worker, server
    return None
