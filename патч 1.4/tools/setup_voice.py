"""Explicit, optional setup of local speech packages and the Russian model.

Running this installer downloads from PyPI and the official Vosk model host.
Normal app startup and dictation never run it or download a model themselves.
"""
import argparse
import os
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.speech import MODEL_NAME, default_model_path, valid_model_path

MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'
MAX_DOWNLOAD = 96 * 1024 * 1024
MAX_EXTRACTED = 256 * 1024 * 1024
MAX_MEMBERS = 2000


def environment_python():
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        raise RuntimeError('Сначала установите приложение через install.bat. Виртуальное окружение .venv не найдено.')
    return python


def download_model(destination):
    """Bounded HTTPS download to a new temporary file, then atomic rename."""
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + '.part')
    request = urllib.request.Request(MODEL_URL, headers={'User-Agent': 'NaryadAI-Voice-Setup/1.0'})
    received = 0
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = urlparse(response.geturl())
        if final_url.scheme != 'https' or final_url.hostname != 'alphacephei.com':
            raise RuntimeError('Загрузка модели перенаправлена на неожиданный адрес.')
        declared = response.headers.get('Content-Length')
        if declared is not None:
            try:
                size = int(declared)
            except ValueError as error:
                raise RuntimeError('Сервер модели сообщил некорректный размер файла.') from error
            if size <= 0 or size > MAX_DOWNLOAD:
                raise RuntimeError('Размер голосовой модели превышает допустимый предел.')
        with partial.open('xb') as output:
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_DOWNLOAD:
                    raise RuntimeError('Загрузка модели превышает допустимый предел.')
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if received == 0 or (declared is not None and received != int(declared)):
            raise RuntimeError('Голосовая модель загрузилась не полностью. Повторите установку.')
    # Both paths belong to a freshly-created temporary setup directory.
    partial.rename(destination)


def extract_model(archive, staging):
    """Validate every ZIP member before writing; no extractall or symlinks."""
    staging = Path(staging).resolve()
    seen = set()
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if not members or len(members) > MAX_MEMBERS:
            raise RuntimeError('Архив модели содержит недопустимое количество файлов.')
        if sum(member.file_size for member in members) > MAX_EXTRACTED:
            raise RuntimeError('Распакованная модель превышает допустимый размер.')
        validated = []
        for member in members:
            # ZipInfo may normalize backslashes on Windows and truncate NULs;
            # inspect the original archive name before accepting that rewrite.
            name = member.orig_filename
            path = PurePosixPath(name)
            reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
            if (not name or '\\' in name or '\x00' in name or path.is_absolute()
                    or any(part in ('.', '..') or ':' in part for part in path.parts)
                    or any(part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved for part in path.parts)
                    or not path.parts or path.parts[0] != MODEL_NAME):
                raise RuntimeError('Архив модели содержит небезопасный путь.')
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError('Архив модели содержит символическую ссылку.')
            destination = (staging / Path(*path.parts)).resolve()
            try:
                destination.relative_to(staging)
            except ValueError as error:
                raise RuntimeError('Путь файла выходит за папку установки.') from error
            key = str(destination).casefold()
            if key in seen:
                raise RuntimeError('Архив модели содержит повторяющийся путь.')
            seen.add(key)
            if member.flag_bits & 1:
                raise RuntimeError('Зашифрованный архив модели не поддерживается.')
            validated.append((member, destination))
        staging.mkdir(parents=True, exist_ok=True)
        for member, destination in validated:
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with source.open(member) as input_file, destination.open('xb') as output:
                while True:
                    chunk = input_file.read(128 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > member.file_size or written > MAX_EXTRACTED:
                        raise RuntimeError('Содержимое архива превышает заявленный размер.')
                    output.write(chunk)
    model = staging / MODEL_NAME
    if not valid_model_path(model):
        raise RuntimeError('В архиве нет необходимых файлов голосовой модели.')
    return model


def install_model(target, downloader=download_model):
    target = Path(target).expanduser().resolve()
    if target.exists() or target.is_symlink():
        if valid_model_path(target):
            print('Русская модель уже установлена:', target)
            return target
        raise RuntimeError('Папка модели уже существует, но неполна. Выберите другую папку через --target. Существующие файлы не изменены.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Cleanup is restricted to this newly-created directory. Existing model
    # directories and application data are never deleted or overwritten.
    with tempfile.TemporaryDirectory(prefix='.naryadai-voice-', dir=target.parent) as temporary:
        stage = Path(temporary).resolve()
        stage.relative_to(target.parent)
        archive = stage / 'model.zip'
        print('Скачиваю русскую модель с официального сайта Vosk (около 45 МБ)…')
        downloader(archive)
        model = extract_model(archive, stage / 'extracted')
        if target.exists() or target.is_symlink():
            raise RuntimeError('Папка модели появилась во время установки. Её файлы оставлены без изменений.')
        model.rename(target)
    print('Русская модель установлена:', target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Дополнительный локальный голосовой ввод. Установка использует интернет, диктовка — нет.')
    parser.add_argument('--model-only', action='store_true', help='Установить только модель, без Python-пакетов')
    parser.add_argument('--check', action='store_true', help='Проверить готовность без установки и загрузки')
    parser.add_argument('--target', type=Path, help='Папка конечной модели; существующая неполная папка не перезаписывается')
    args = parser.parse_args(argv)
    target = args.target or default_model_path()
    try:
        if args.check:
            ready = valid_model_path(target)
            print('Модель найдена.' if ready else 'Модель не установлена:', target)
            if not args.model_only:
                result = subprocess.run([str(environment_python()), '-c',
                    'import vosk, sounddevice; print("Speech packages OK")'], cwd=ROOT, check=False)
                ready = ready and result.returncode == 0
            return 0 if ready else 2
        if not args.model_only:
            python = environment_python()
            print('Устанавливаю дополнительные пакеты. Обычный ввод отчёта продолжит работать при ошибке установки.')
            result = subprocess.run([str(python), '-m', 'pip', 'install', '-r',
                                     str(ROOT / 'requirements-voice.txt')], cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
            result = subprocess.run([str(python), '-m', 'pip', 'check'], cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
        install_model(target)
        print('Готово. Речь преобразуется локально. Проверьте распознанные числа и названия перед отправкой отчёта.')
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print('Не удалось установить голосовой ввод:', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
