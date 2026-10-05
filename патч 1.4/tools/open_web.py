"""Open the shared server in the browser using the same address as the desktop client."""
import json
import sys
import webbrowser
from client_launcher import ROOT, normalize_url


def main():
    config = ROOT / 'client_config.json'
    previous = ''
    if config.exists():
        previous = json.loads(config.read_text(encoding='utf-8-sig')).get('server', '')
    if not previous or '--change-server' in sys.argv:
        previous = normalize_url(input(f'Общий адрес сервера [{previous}]: ').strip() or previous)
        config.write_text(json.dumps({'server': previous}, ensure_ascii=False, indent=2), encoding='utf-8')
    url = normalize_url(previous)
    print('Открываю ' + url)
    print('На телефоне откройте этот же адрес. Учётные записи и наряды общие с программой Windows.')
    if not webbrowser.open(url):
        print('Не удалось открыть браузер автоматически. Скопируйте адрес в браузер.')
        return 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print('Подключение:', error)
        raise SystemExit(1)
