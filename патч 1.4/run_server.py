import argparse,logging
from pathlib import Path
from server.config import Settings
from server.api import create_app

def main():
    parser=argparse.ArgumentParser(description='Общий сервер НарядAI + AnythingLLM')
    parser.add_argument('--config',type=Path,default=None);args=parser.parse_args()
    settings=Settings.load(args.config)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    print(f'НарядAI: сервер запускается на порту {settings.port}. Не закрывайте это окно.')
    print('ИИ: '+(('обработчик на домашнем ПК' if settings.ai_mode=='remote_worker' else 'AnythingLLM, '+settings.workspace) if settings.ai_enabled else 'отключён'))
    import uvicorn
    uvicorn.run(create_app(settings),host=settings.host,port=settings.port,workers=1,access_log=False)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as e:print('Не удалось запустить сервер:',e);raise SystemExit(1)
