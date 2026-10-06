import getpass,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from worker import Worker
from server.config import Settings
from server.anythingllm import AnythingLLM

def main():
    print('Облачный сервер должен быть уже развёрнут. AnythingLLM — запущен на этом ПК.')
    server=input('Адрес сервера https://...onrender.com: ').strip().rstrip('/')
    token=getpass.getpass('AI_WORKER_TOKEN из настроек Render (ввод скрыт): ').strip()
    settings=Settings.load()
    if not settings.chat_workspace:raise ValueError('Сначала configure_server.bat: он настроит отдельный чат администратора.')
    worker=Worker(server,token,AnythingLLM(settings));health=worker.request('/health')
    if 'admin_chat' not in health.get('features',[]):raise ValueError('На Render развёрнута старая версия. Выполните Manual Deploy → Deploy latest commit для cloud-1.4.')
    worker.request('/api/ai/heartbeat',{})
    (ROOT/'worker_config.json').write_text(json.dumps({'server':server,'token':token},ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'client_config.json').write_text(json.dumps({'server':server},indent=2),encoding='utf-8')
    print('Подключение проверено. Запустите start_worker.bat и оставьте окно открытым.')
    if not health.get('ai_enabled'):print('ИИ сейчас выключен. Войдите администратором на сайт и включите его в центре управления.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,PermissionError) as e:print('Настройка не завершена:',e);raise SystemExit(1)
