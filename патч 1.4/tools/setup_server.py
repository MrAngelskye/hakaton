"""Локальная настройка: ключ вводится на ПК пользователя, а не в чате."""
import getpass,json,socket,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.config import Settings
from server.anythingllm import AnythingLLM,AIError

def ask(prompt,default=''):
    answer=input(prompt+(f' [{default}]' if default else '')+': ').strip();return answer or default

def choose_workspace(ai,previous=''):
    spaces=ai.workspaces()
    print('\n0 — создать отдельное пространство NaryadAI для проверки отчётов')
    default='0'
    for i,w in enumerate(spaces,1):
        print(f"{i} — {w.get('name',w['slug'])} ({w['slug']})")
        if w['slug']==previous:default=str(i)
    choice=ask('Номер рабочего пространства',default)
    if not choice.isdigit() or not 0<=int(choice)<=len(spaces):raise ValueError('Выберите номер из списка.')
    return ai.create_workspace() if choice=='0' else spaces[int(choice)-1]['slug']

def main():
    print('Настройка сервера НарядAI. AnythingLLM должен быть запущен на этом ПК.')
    target=ROOT/'server_config.json';old=json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else {}
    url=ask('Адрес AnythingLLM (без /api)',old.get('base_url','http://127.0.0.1:3001'))
    key=getpass.getpass('API-ключ AnythingLLM (ввод скрыт; Enter — оставить прежний): ').strip() or old.get('api_key','')
    label=ask('Название выбранной модели для подписи результата',old.get('model_label','Модель AnythingLLM'))
    images=ask('Отправлять фотографии модели? Только если она поддерживает изображения (да/нет)','да' if old.get('send_images') else 'нет').lower() in ('да','yes','y')
    directory=ask('Папка общей базы и фотографий',old.get('data_dir','server_data'))
    data={'data_dir':directory,'base_url':url,'api_key':key,'workspace':old.get('workspace','naryadai'),'ai_enabled':True,
          'timeout':180,'send_images':images,'model_label':label,'host':'0.0.0.0','port':8000}
    # Проверить настройки до записи; содержимое ключа не печатается.
    scratch=ROOT/'server_config.pending.json';scratch.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        s=Settings.load(scratch);ai=AnythingLLM(s)
        data['workspace']=choose_workspace(ai,old.get('workspace',''));s.workspace=data['workspace'];ai.check_workspace()
        scratch.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        scratch.replace(target)
    finally:scratch.unlink(missing_ok=True)
    print('Рабочее пространство подключено. Настройки сохранены в server_config.json.')
    print('Теперь запустите check_ai.bat, затем start_server.bat.')
    print('Клиент на этом ПК: http://127.0.0.1:8000')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as e:print('Настройка не завершена:',e);raise SystemExit(1)
