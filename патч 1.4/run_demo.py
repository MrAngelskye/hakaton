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
    parser.add_argument('--dataset','--history',dest='dataset',action='store_true',help='Импортировать включённый учебный набор 608 нарядов только в новую папку')
    args=parser.parse_args()
    if args.dataset:
        from tools.import_demo import import_demo
        try:info=import_demo(args.data_dir)
        except (ValueError,OSError) as e:parser.error(str(e))
        print('Учебный набор: '+str(info['counts']['tasks'])+' нарядов; все фото и оценки синтетические.')
    settings=Settings(data_dir=args.data_dir,ai_enabled=False,ai_mode='local',seed_demo=True)
    app=create_app(settings)
    print(f'Демонстрационные данные: {args.data_dir.resolve()}')
    print(f'Откройте http://{args.host}:{args.port}. ИИ отключён: приёмка вручную.')
    print('Демо-аккаунты: master / worker1 / admin, пароль '+('DemoOnly-2026!' if args.dataset else '1234')+'. Для предприятия используйте настроенный HTTPS-сервер.')
    uvicorn.run(app,host=args.host,port=args.port)


if __name__=='__main__':main()
