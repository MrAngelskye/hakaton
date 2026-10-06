"""Remote support CLI. Authenticate normally; never store passwords or expose database keys."""
import getpass,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.remote import RemoteStore
ROOT=Path(__file__).resolve().parents[1]
def display(value):print(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))
def main():
    default='https://hakaton-cj24.onrender.com'
    config=ROOT/'client_config.json'
    if config.exists():
        try:default=json.loads(config.read_text(encoding='utf-8-sig')).get('server',default)
        except (ValueError,OSError):pass
    server=input('Адрес сервера ['+default+']: ').strip() or default
    store=RemoteStore(server);store.authenticate(input('Логин администратора [admin]: ').strip() or 'admin',getpass.getpass('Пароль: '),'admin')
    print('Консоль НарядAI. /help — команды; /watch — журнал; /exit — выйти.');pending=None
    try:
        while True:
            command=input('НарядAI > ').strip()
            if not command:continue
            if command=='/exit':break
            if command=='/watch':
                print('Журнал действий. Ctrl+C — вернуться к командам.');seen=set()
                try:
                    while True:
                        rows=store.request('/api/admin/events?limit=30')['items']
                        for row in reversed(rows):
                            key=(row['id'],row['created'],row['action'])
                            if key not in seen:display(row);seen.add(key)
                        time.sleep(3)
                except KeyboardInterrupt:print('\nНаблюдение остановлено.')
                continue
            if not pending or pending['command']!=command:pending={'command':command,'request_id':uuid.uuid4().hex}
            try:display(store.request('/api/admin/command',pending)['output']);pending=None
            except (OSError,ValueError,PermissionError) as e:print('Ошибка:',e,'Повтор той же команды сохранит идентификатор запроса.')
    finally:
        try:store.request('/api/logout',{})
        except Exception:pass
        store._cache.cleanup()
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,PermissionError,EOFError,KeyboardInterrupt) as e:print('\nКонсоль завершена:',e)
