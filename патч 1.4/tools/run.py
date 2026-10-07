"""Launch existing scripts with the installed project interpreter."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.environment import resolve_python


def launch(project, script, arguments=(), *, web_first=False, web_fallback=False, system_fallback=False):
    project = Path(project).resolve()
    target = (project / script).resolve()
    if not target.is_relative_to(project) or not target.is_file():
        raise RuntimeError('Файл запуска не найден в папке проекта.')
    python = resolve_python(project, web_first=web_first, web_fallback=web_fallback, system_fallback=system_fallback)
    return subprocess.run([str(python), str(target), *arguments], cwd=project, check=False).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', action='store_true', help='Показать выбранный интерпретатор')
    parser.add_argument('--web-first', action='store_true')
    parser.add_argument('--web-fallback', action='store_true')
    parser.add_argument('--system-fallback', action='store_true')
    parser.add_argument('script', nargs='?')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    options = dict(web_first=args.web_first, web_fallback=args.web_fallback, system_fallback=args.system_fallback)
    try:
        if args.python:
            print(resolve_python(ROOT, **options));return 0
        if not args.script:
            parser.error('Нужен файл запуска или --python')
        return launch(ROOT, args.script, args.arguments, **options)
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr);return 1
    except KeyboardInterrupt:
        print('\nЗапуск остановлен.', file=sys.stderr);return 130


if __name__ == '__main__':
    raise SystemExit(main())
