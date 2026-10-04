"""Адрес сохраняется один раз. При следующих запусках подключение автоматическое."""
import json,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
from urllib.error import URLError,HTTPError

ROOT=Path(__file__).resolve().parents[1]

def normalize_url(value):
    value=value.strip().rstrip('/')
    if '://' not in value:value='https://'+value
    parsed=urlparse(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError('Введите адрес сервера, например https://naryadai.onrender.com.')
    if parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1'):
        print('HTTP предназначен только для доверенной локальной сети. Для облака используйте HTTPS.')
    return value

def wait_for_server(url,seconds=100):
    deadline=time.monotonic()+seconds
    print('Подключение к серверу. После простоя первый запуск может занять около минуты…',flush=True)
    while True:
        try:
            with urlopen(url+'/health',timeout=15) as response:
                info=json.loads(response.read(4096))
                if info.get('ok') is True and str(info.get('version','')).startswith(('1.3','1.4')):return
                raise ValueError('По этому адресу работает другой сервер.')
        except (URLError,HTTPError,TimeoutError,json.JSONDecodeError,OSError):
            if time.monotonic()>=deadline:raise OSError('Не удалось подключиться. Проверьте интернет и адрес сервера.') from None
            time.sleep(2)

def main():
    cfg=ROOT/'client_config.json';previous=''
    if cfg.exists():previous=json.loads(cfg.read_text(encoding='utf-8-sig')).get('server','')
    if not previous or '--change-server' in sys.argv:
        print('Сетевой клиент НарядAI. Укажите общий адрес Render для обоих ПК.')
        previous=normalize_url(input(f'Адрес сервера [{previous}]: ').strip() or previous)
        cfg.write_text(json.dumps({'server':previous},ensure_ascii=False,indent=2),encoding='utf-8')
    url=normalize_url(previous);wait_for_server(url)
    return subprocess.call([sys.executable,str(ROOT/'main.py'),'--server',url],cwd=ROOT)

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError) as e:print('Подключение:',e);raise SystemExit(1)
