"""Настройки находятся только на сервере; секрет не отправляется клиентам."""
import json,os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]

@dataclass
class Settings:
    data_dir: Path
    base_url: str='http://127.0.0.1:3001'
    api_key: str=''
    workspace: str='naryadai'
    chat_workspace: str=''
    ai_enabled: bool=True
    timeout: int=180
    send_images: bool=False
    model_label: str='Модель рабочего пространства AnythingLLM'
    host: str='0.0.0.0'
    port: int=8000
    ai_mode: str='local'
    database_url: str=''
    supabase_url: str=''
    supabase_secret_key: str=''
    storage_bucket: str='naryadai-reports'
    worker_token: str=''
    bootstrap_password: str=''
    offline_wait: int=120
    database_pool_size: int=8
    acceptance_minutes: int=10
    urgent_acceptance_minutes: int=3
    deadline_reminder_minutes: int=30
    overdue_repeat_minutes: int=30
    notification_webhook: str=''
    notification_webhook_key: str=''

    def validate_case(self):
        if type(self.database_pool_size) is not int or not 1<=self.database_pool_size<=32:raise ValueError('Размер пула PostgreSQL: 1–32.')
        for value in (self.acceptance_minutes,self.urgent_acceptance_minutes,self.deadline_reminder_minutes,self.overdue_repeat_minutes):
            if type(value) is not int or not 1<=value<=1440:raise ValueError('Пороги уведомлений: 1–1440 минут.')
        if self.notification_webhook:
            url=urlparse(self.notification_webhook)
            if url.scheme!='https' or not url.hostname or url.username or url.password or len(self.notification_webhook_key)<32:raise ValueError('Webhook: HTTPS-адрес и ключ подписи не короче 32 символов.')

    @classmethod
    def load(cls,path=None):
        if os.environ.get('DATABASE_URL') and path is None:
            from psycopg.conninfo import conninfo_to_dict
            try:database=conninfo_to_dict(os.environ['DATABASE_URL'])
            except Exception:raise ValueError('Некорректный DATABASE_URL.') from None
            if database.get('sslmode') not in ('require','verify-ca','verify-full'):raise ValueError('В DATABASE_URL включите sslmode=require или verify-full.')
            if os.environ.get('AI_ENABLED','true').lower() not in ('true','false'):raise ValueError('AI_ENABLED: true или false.')
            obj=cls(data_dir=Path('/tmp/naryadai'),ai_mode='remote_worker',database_url=os.environ['DATABASE_URL'],
                    supabase_url=os.environ.get('SUPABASE_URL',''),supabase_secret_key=os.environ.get('SUPABASE_SECRET_KEY',''),
                    worker_token=os.environ.get('AI_WORKER_TOKEN',''),bootstrap_password=os.environ.get('BOOTSTRAP_PASSWORD',''),
                    port=int(os.environ.get('PORT','8000')),ai_enabled=os.environ.get('AI_ENABLED','true').lower()=='true')
            if not obj.supabase_url.startswith('https://') or not obj.supabase_secret_key:raise ValueError('Задайте SUPABASE_URL и SUPABASE_SECRET_KEY на сервере.')
            if len(obj.worker_token)<32:raise ValueError('AI_WORKER_TOKEN должен содержать не меньше 32 символов.')
            if len(obj.bootstrap_password)<12:raise ValueError('BOOTSTRAP_PASSWORD должен содержать не меньше 12 символов.')
            for field,variable in [('database_pool_size','DATABASE_POOL_SIZE'),('acceptance_minutes','ACCEPTANCE_MINUTES'),('urgent_acceptance_minutes','URGENT_ACCEPTANCE_MINUTES'),('deadline_reminder_minutes','DEADLINE_REMINDER_MINUTES'),('overdue_repeat_minutes','OVERDUE_REPEAT_MINUTES')]:
                if variable in os.environ:setattr(obj,field,int(os.environ[variable]))
            obj.notification_webhook=os.environ.get('NOTIFICATION_WEBHOOK','');obj.notification_webhook_key=os.environ.get('NOTIFICATION_WEBHOOK_KEY','')
            obj.validate_case()
            return obj
        p=Path(path or os.environ.get('NARYADAI_SERVER_CONFIG') or ROOT/'server_config.json')
        if not p.is_file():raise ValueError('Сначала запустите configure_server.bat — он создаст server_config.json.')
        data=json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict):raise ValueError('Настройки сервера должны быть JSON-объектом.')
        if set(data)-set(cls.__dataclass_fields__):raise ValueError('В настройках сервера есть неизвестные поля.')
        if not isinstance(data.get('data_dir','server_data'),str):raise ValueError('data_dir должен быть строкой с путём к папке.')
        directory=Path(data.get('data_dir','server_data'))
        if not directory.is_absolute():directory=p.parent/directory
        obj=cls(data_dir=directory,**{k:v for k,v in data.items() if k!='data_dir'})
        if not all(isinstance(v,str) for v in (obj.base_url,obj.workspace,obj.chat_workspace,obj.api_key,obj.model_label,obj.host)):
            raise ValueError('Адрес, workspace, ключ, модель и host должны быть строками.')
        url=urlparse(obj.base_url)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
            raise ValueError('Некорректный адрес AnythingLLM.')
        obj.base_url=obj.base_url.rstrip('/')
        if obj.base_url.endswith('/api'):obj.base_url=obj.base_url[:-4]
        if not obj.workspace or '/' in obj.workspace:raise ValueError('Укажите slug рабочего пространства, например naryadai.')
        if '/' in obj.chat_workspace:raise ValueError('Некорректный slug рабочего пространства чата.')
        if obj.chat_workspace and obj.chat_workspace==obj.workspace:raise ValueError('Для чата и проверки отчётов нужны разные рабочие пространства.')
        if type(obj.ai_enabled) is not bool or type(obj.send_images) is not bool:raise ValueError('ai_enabled и send_images должны быть true/false.')
        if type(obj.timeout) is not int or type(obj.port) is not int or not 10<=obj.timeout<=600 or not 1<=obj.port<=65535:raise ValueError('Проверьте timeout и port.')
        if obj.ai_mode not in ('local','remote_worker'):raise ValueError('ai_mode: local или remote_worker.')
        if obj.ai_mode=='remote_worker' and len(obj.worker_token)<32:raise ValueError('Настройте AI_WORKER_TOKEN.')
        if obj.ai_enabled and obj.ai_mode=='local' and not obj.api_key:raise ValueError('В server_config.json не указан API-ключ AnythingLLM.')
        return obj
