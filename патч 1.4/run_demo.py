"""Local web/PWA demo with a separate database and explicit manual review."""
import argparse
from pathlib import Path
import uvicorn
from server.api import create_app
from server.config import Settings


def main():
    parser=argparse.ArgumentParser(description='НарядAI: браузерная демонстрация без подключения модели')
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parent/'demo_data')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8841)
    parser.add_argument('--history',action='store_true',help='Добавить 540 явно синтетических нарядов за 90 дней только в новую демо-базу')
    args=parser.parse_args()
    if args.history:
        from tools.demo_history import history_is_seeded
        if args.data_dir.exists() and (not args.data_dir.is_dir() or any(args.data_dir.iterdir())) and not history_is_seeded(args.data_dir):
            parser.error('Для --history выберите новую --data-dir. Существующая база без маркера демо-истории не изменяется.')
    settings=Settings(data_dir=args.data_dir,ai_enabled=False,ai_mode='local')
    app=create_app(settings)
    if args.history:
        from tools.demo_history import populate_demo_history
        marker=populate_demo_history(app.state.store,allow_demo=True)
        print(f"Синтетическая история: {marker['count']} нарядов за {marker['days']} дней; фото и ИИ не имитируются.")
    print(f'Демонстрационные данные: {args.data_dir.resolve()}')
    print(f'Откройте http://{args.host}:{args.port}. ИИ отключён: приёмка вручную.')
    print('Демо-аккаунты: master / worker1 / admin, пароль 1234. Для предприятия используйте настроенный HTTPS-сервер.')
    uvicorn.run(app,host=args.host,port=args.port)


if __name__=='__main__':main()
