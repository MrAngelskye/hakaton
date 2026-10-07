"""Installer with automatic short environments; no system changes."""
import argparse
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.environment import choose_environment, environment_python, path_units, PYSIDE_RESOURCE, save_environment


def install(project=ROOT, check_only=False):
    project = Path(project).resolve()
    try:
        env = choose_environment(project)
        print('Окружение Python:', env, flush=True)
        if env != project / '.venv':
            print('Длинный путь проекта: зависимости будут установлены в короткую папку автоматически.', flush=True)
        print('Длина пути ресурса PySide6:', path_units(env / PYSIDE_RESOURCE), flush=True)
        if check_only:
            print('Проверка пройдена. Установка не запускалась.');return 0
        python = environment_python(env)
        commands = [
            [sys.executable, '-m', 'venv', str(env)],
            [str(python), '-m', 'pip', 'install', '-r', str(project / 'requirements.txt')],
            [str(python), '-m', 'pip', 'check'],
            [str(python), '-c', 'from PySide6.QtWidgets import QApplication; print("PySide6 OK")'],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=project, check=False)
            if result.returncode:
                print('Установка не завершена. Повторите install.bat после исправления указанной ошибки. Данные приложения не удалены.')
                return result.returncode
        # Publish only a fully installed and verified interpreter.
        save_environment(project, env)
        print('Установка завершена. Запуск: start.bat.', flush=True)
        return 0
    except (OSError, RuntimeError) as error:
        print('Не удалось выполнить установку:', error);return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Проверить выбранный путь без установки')
    raise SystemExit(install(check_only=parser.parse_args().check))
