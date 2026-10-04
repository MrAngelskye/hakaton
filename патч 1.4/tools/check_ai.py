import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.config import Settings
from server.anythingllm import AnythingLLM

def main():
    settings=Settings.load();ai=AnythingLLM(settings)
    print('Проверка реального ответа AnythingLLM. Первый ответ может занять несколько минут.')
    ai.check_workspace()
    task={'title':'Проверить привод конвейера','description':'Осмотреть крепления, проверить контакты и выполнить контрольный запуск.',
          'equipment':'Конвейер СЛ-01','site':'Сборочный цех','kind':'Плановая','duration':1}
    report={'work':'Проверены контакты, подтянуты крепления. Выполнен контрольный запуск на 10 минут.',
            'result':'Конвейер работает ровно. Посторонних звуков нет. Замечаний при запуске не обнаружено.',
            'defect':'D-00 · Дефектов нет','hours':1,'materials':[],'photos':[]}
    with tempfile.TemporaryDirectory() as folder:r=ai.review(task,report,Path(folder))
    print('Модель ответила. Формат и сумма оценок проверены:')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    print('Можно запускать совместный тест.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as e:print('ИИ пока не подключён:',e);raise SystemExit(1)
