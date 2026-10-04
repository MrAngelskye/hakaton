"""Обработчик на ПК с AnythingLLM. Подключения к серверу исходящие HTTPS."""
import json,logging,threading,time,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse,quote
from server.config import Settings
from server.anythingllm import AnythingLLM,AIError

ROOT=Path(__file__).resolve().parent
LOG=logging.getLogger('worker')

class Worker:
    def __init__(self,server,token,ai):
        p=urlparse(server)
        if p.scheme!='https' and not (p.scheme=='http' and p.hostname in ('127.0.0.1','localhost')):raise ValueError('Облачный адрес должен начинаться с https://.')
        if not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):raise ValueError('Некорректный адрес сервера.')
        if len(token)<32:raise ValueError('Ключ обработчика ИИ должен содержать не меньше 32 символов.')
        self.server=server.rstrip('/');self.token=token;self.ai=ai;self._prefer_chat=False
    def request(self,path,payload=None,lease=None,binary=False):
        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
        if lease:headers['X-Job-Lease']=lease
        data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
        req=Request(self.server+path,data=data,headers=headers,method='POST' if data is not None else 'GET')
        try:
            with urlopen(req,timeout=90) as r:
                raw=r.read(10*1024*1024+1)
                if len(raw)>10*1024*1024:raise OSError('Ответ сервера слишком большой.')
                return raw if binary else json.loads(raw)
        except HTTPError as e:
            if e.code in (401,403):raise PermissionError('Сервер отклонил ключ обработчика ИИ.') from None
            if e.code==400:raise ValueError('Задание уже завершено либо сервер отклонил результат.') from None
            raise OSError(f'Сервер приложения вернул HTTP {e.code}.') from None
        except (URLError,TimeoutError):raise OSError('Сервер приложения пока недоступен; подключение будет повторено.') from None
    def run_once(self):
        if self._prefer_chat:
            self._prefer_chat=False
            if self.run_chat_once():return True
        job=self.request('/api/ai/claim',{})['job']
        if not job:return self.run_chat_once()
        self._prefer_chat=True
        report=job['report'];rid=report['id'];lease=job['lease'];result=None;error=''
        LOG.info('Получен отчёт ОТ-%04d',rid)
        with tempfile.TemporaryDirectory(prefix='naryadai-ai-') as folder:
            folder=Path(folder)
            try:
                if self.ai.settings.send_images:
                    for name in report.get('before_photos',[])+report['photos']:
                        if Path(name).name!=name:raise AIError('Некорректное имя фотографии.')
                        raw=self.request(f'/api/ai/photo/{rid}/'+quote(name,safe=''),lease=lease,binary=True)
                        (folder/name).write_bytes(raw)
                result=self.ai.review(job['task'],report,folder)
            except (AIError,OSError) as e:error=str(e)
            body={'lease':lease,'result':result,'error':error,'model':self.ai.settings.model_label[:200]}
            for attempt in range(3):
                try:self.request(f'/api/ai/result/{rid}',body);break
                except OSError:
                    if attempt==2:raise
                    time.sleep(2)
        LOG.info('Отчёт ОТ-%04d передан мастеру%s',rid,' с оценкой ИИ' if result else ' для ручной проверки')
        return True
    def run_chat_once(self):
        job=self.request('/api/ai/chat/claim',{})['job']
        if not job:return False
        LOG.info('Получено сообщение администратора')
        try:answer=self.ai.chat(job['message'],job['history'],job['conversation_id']);error=''
        except (AIError,OSError) as e:answer='';error=str(e)
        body={'lease':job['lease'],'answer':answer,'error':error,'model':self.ai.settings.model_label[:200]}
        for attempt in range(3):
            try:self.request('/api/ai/chat/result/'+job['id'],body);break
            except OSError:
                if attempt==2:raise
                time.sleep(2)
        LOG.info('Ответ чата передан в приложение')
        return True
    def run(self):
        stop=threading.Event()
        def heartbeat():
            while not stop.is_set():
                try:self.request('/api/ai/heartbeat',{})
                except (OSError,ValueError,PermissionError):pass
                stop.wait(15)
        threading.Thread(target=heartbeat,daemon=True).start()
        try:
            while True:
                try:busy=self.run_once()
                except PermissionError:raise
                except (OSError,ValueError) as e:LOG.warning('%s',e);busy=False
                if not busy:time.sleep(5)
        except KeyboardInterrupt:print('Обработчик остановлен.')
        finally:stop.set()

def main():
    cfg=ROOT/'worker_config.json'
    if not cfg.exists():raise ValueError('Сначала запустите configure_worker.bat.')
    data=json.loads(cfg.read_text(encoding='utf-8-sig'));settings=Settings.load()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    Worker(data['server'],data['token'],AnythingLLM(settings)).run()

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,PermissionError) as e:print('Обработчик ИИ:',e);raise SystemExit(1)
