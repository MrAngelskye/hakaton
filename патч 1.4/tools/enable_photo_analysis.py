import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'server_config.json'
if not p.exists():raise SystemExit('Сначала настройте AnythingLLM через configure_server.bat.')
data=json.loads(p.read_text(encoding='utf-8-sig'));data['send_images']=True;data['timeout']=600
p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Отправка фотографий включена; тайм-аут не меньше 600 секунд.')
print('Выберите модель с поддержкой изображений в пространстве отчётов AnythingLLM. Перезапустите start_worker.bat.')
