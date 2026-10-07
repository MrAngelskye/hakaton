"""Resolve the project interpreter without relocating application data."""
import hashlib
import json
import os
import sys
from pathlib import Path

MARKER = '.naryadai-runtime.json'
PYSIDE_RESOURCE = (
    'Lib/site-packages/PySide6/qml/Qt/labs/assetdownloader/objects-RelWithDebInfo/'
    'QmlAssetDownloaderPrivate_resources_1/.qt/rcc/'
    'qrc_qmake_Qt_labs_assetdownloader_init.cpp.obj'
)


def path_units(path):
    return len(str(path).encode('utf-16-le')) // 2


def project_identity(project):
    return os.path.normcase(str(Path(project).resolve()))


def environment_python(environment):
    return Path(environment) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def choose_environment(project, *, windows=None, home=None):
    project = Path(project).resolve()
    local = project / '.venv'
    windows = os.name == 'nt' if windows is None else windows
    if not windows or path_units(local / PYSIDE_RESOURCE) < 260:
        return local
    identity = project_identity(project) + '\n' + str(Path(sys.executable).resolve())
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]
    selected = ((Path(home) if home is not None else Path.home()) / '.nai' / digest).resolve()
    if path_units(selected / PYSIDE_RESOURCE) >= 260:
        raise RuntimeError('Даже папка профиля слишком длинная. Распакуйте проект в короткую папку, например C:\\NaryadAI, и снова запустите install.bat.')
    return selected


def save_environment(project, environment):
    project = Path(project).resolve()
    marker = project / MARKER
    temporary = marker.with_suffix('.json.tmp')
    data = {'schema': 1, 'project': project_identity(project), 'environment': str(Path(environment).resolve())}
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(marker)


def selected_environment(project):
    project = Path(project).resolve()
    marker = project / MARKER
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding='utf-8'))
            if data.get('schema') != 1 or data.get('project') != project_identity(project):
                raise ValueError('Project moved or marker version changed')
            selected = Path(data['environment'])
            if not selected.is_absolute():
                raise ValueError('Environment must be absolute')
            return selected
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise RuntimeError('Папка проекта перенесена или настройки окружения повреждены. Запустите install.bat заново; данные приложения сохранятся.') from error
    return project / '.venv'


def resolve_python(project, *, web_first=False, web_fallback=False, system_fallback=False):
    project = Path(project).resolve()
    web = environment_python(project / '.webvenv')
    if web_first and web.is_file():
        return web
    selected = environment_python(selected_environment(project))
    if selected.is_file():
        return selected
    if web_fallback and web.is_file():
        return web
    if system_fallback:
        return Path(sys.executable)
    raise RuntimeError('Окружение приложения не найдено. Запустите install.bat, затем повторите запуск. Для веб-версии используйте install_web.bat.')
