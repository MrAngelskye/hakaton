"""Windows installer preflight and dependency setup; never changes system settings."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Longest resource in the pinned PySide6 6.11.2 Windows wheel (RECORD).
PYSIDE_RESOURCE = (
    'Lib/site-packages/PySide6/qml/Qt/labs/assetdownloader/objects-RelWithDebInfo/'
    'QmlAssetDownloaderPrivate_resources_1/.qt/rcc/'
    'qrc_qmake_Qt_labs_assetdownloader_init.cpp.obj'
)


def windows_long_paths_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
            return winreg.QueryValueEx(key, 'LongPathsEnabled')[0] == 1
    except (ImportError, OSError):
        return False


def resource_path_length(project):
    path = project / '.venv' / PYSIDE_RESOURCE
    return len(str(path).encode('utf-16-le')) // 2


def check_path(project, long_paths):
    length = resource_path_length(project)
    if length < 260 or long_paths:
        return True
    print('Папка проекта слишком глубоко вложена для установки PySide6.')
    print(f'Путь одного из файлов составит {length} символов; обычный предел Windows — 259.')
    print('Распакуйте чистый архив в короткую папку, например:')
    print(Path.home() / 'NaryadAI')
    print('Затем снова запустите install.bat из папки проекта.')
    print('Частично установленную .venv не переносите. Данные приложения не удаляются.')
    return False


def install(project=ROOT, check_only=False):
    if os.name == 'nt' and not check_path(project, windows_long_paths_enabled()):
        return 2
    if check_only:
        print('Проверка пути пройдена. Установка не запускалась.')
        return 0
    env = project / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    commands = [
        [sys.executable, '-m', 'venv', str(env)],
        [str(python), '-m', 'pip', 'install', '-r', str(project / 'requirements.txt')],
        [str(python), '-m', 'pip', 'check'],
        [str(python), '-c', 'from PySide6.QtWidgets import QApplication; print("PySide6 OK")'],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, cwd=project, check=False)
        except OSError as error:
            print('Не удалось выполнить установку:', error)
            return 1
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Только проверить путь, без установки')
    raise SystemExit(install(check_only=parser.parse_args().check))
