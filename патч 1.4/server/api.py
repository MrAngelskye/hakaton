"""Один сервер приложения для всех клиентов. Запуск через run_server.py."""
import base64,hashlib,hmac,inspect,json,logging,mimetypes,secrets,sqlite3,tempfile,threading,time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import Response,JSONResponse,HTMLResponse
from pydantic import BaseModel,Field,ConfigDict
from server.store import ServerStore
from server.anythingllm import AnythingLLM,AIError,parse_verdict

LOG=logging.getLogger('naryadai')
MAX_BODY=36*1024*1024
WRITE_METHODS={'create_task','claim','reschedule','transition','submit','review','add_user','set_active','reset_password','support_update_task','set_shift'}
READ_METHODS={'task','events','pauses','shift','free_slots','employee_status'}

class LoginBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(max_length=100)
    password:str=Field(max_length=300)
    role:str

class CallBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    args:list=Field(default_factory=list,max_length=12)
    kwargs:dict=Field(default_factory=dict)
    request_id:str=Field(min_length=16,max_length=100)
    photos:list=Field(default_factory=list,max_length=3)

class ResultBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    lease:str=Field(min_length=32,max_length=100)
    result:dict|None=None
    error:str=Field(default='',max_length=1000)
    model:str=Field(default='Модель AnythingLLM',min_length=1,max_length=200)

class ChatSend(BaseModel):
    model_config=ConfigDict(extra='forbid')
    conversation_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    message:str=Field(min_length=1,max_length=4000)

class NewChat(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')

class ChatResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    lease:str=Field(min_length=32,max_length=100)
    answer:str=Field(default='',max_length=20000)
    error:str=Field(default='',max_length=1000)
    model:str=Field(default='Модель AnythingLLM',max_length=200)

def create_app(settings,provider=None):
    if settings.database_url:
        from server.postgres import PostgresStore
        from server.storage import SupabaseStorage
        storage=SupabaseStorage(settings.supabase_url,settings.supabase_secret_key,settings.storage_bucket);storage.ensure_bucket()
        store=PostgresStore(settings.data_dir,settings,storage)
    else:store=ServerStore(settings.data_dir,settings)
    ai=provider or AnythingLLM(settings)
    remote=settings.ai_mode=='remote_worker'
    if remote and len(settings.worker_token)<32:raise ValueError('Настройте ключ удалённого обработчика ИИ.')
    if remote:
        from server.remote_jobs import RemoteJobs
        jobs=RemoteJobs(store,settings)
    from server.chat import AdminChat
    chat=AdminChat(store,settings)
    stopping=threading.Event();rpc_lock=threading.Lock();login_lock=threading.Lock();attempts={}

    def ai_loop():
        while not stopping.is_set():
            try:
                if remote:
                    with rpc_lock:jobs.expire();chat.expire()
                    stopping.wait(5);continue
                with rpc_lock:job=store.take_ai_job()
                if not job:
                    with rpc_lock:chat_job=chat.claim()
                    if not chat_job:stopping.wait(.5);continue
                    try:answer=ai.chat(chat_job['message'],chat_job['history'],chat_job['conversation_id']);error=''
                    except AIError as e:answer='';error=str(e)
                    except Exception:answer='';error='Не удалось получить ответ ИИ. Проверьте AnythingLLM.'
                    if stopping.is_set():return
                    with rpc_lock:chat.result(chat_job['id'],chat_job['lease'],answer,error,settings.model_label)
                    continue
                task,report=job
                try:result=ai.review(task,report,store.photos);error=''
                except AIError as e:result=None;error=str(e)
                except Exception:
                    LOG.exception('Ошибка обработки ИИ');result=None;error='Не удалось обработать отчёт. Мастер может проверить его вручную.'
                if stopping.is_set():return  # После остановки запрос восстановится из очереди при следующем запуске.
                with rpc_lock:store.finish_ai(report['id'],result,error)
            except Exception:
                LOG.exception('Ошибка очереди ИИ');stopping.wait(1)

    @asynccontextmanager
    async def lifespan(app):
        thread=threading.Thread(target=ai_loop,name='report-ai',daemon=True)
        thread.start()
        try:yield
        finally:stopping.set();thread.join(timeout=2)

    app=FastAPI(title='НарядAI · сервер',version='1.4',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.provider=ai;app.state.chat=chat

    @app.middleware('http')
    async def body_limit(request,call_next):
        try:declared=int(request.headers.get('content-length','0'))
        except ValueError:return JSONResponse({'detail':'Некорректный размер запроса.'},status_code=400)
        if declared>MAX_BODY:return JSONResponse({'detail':'Слишком большой запрос.'},status_code=413)
        if request.method=='POST':
            raw=await request.body()
            if len(raw)>MAX_BODY:return JSONResponse({'detail':'Слишком большой запрос.'},status_code=413)
        response=await call_next(request);response.headers['Cache-Control']='no-store';return response

    @app.exception_handler(PermissionError)
    async def permission_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=403)
    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)
    @app.exception_handler(OSError)
    async def storage_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=503)
    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request,exc):
        LOG.exception('База данных временно недоступна');return JSONResponse({'detail':'База временно занята. Повторите действие.'},status_code=503)

    if settings.database_url:
        import psycopg
        app.add_exception_handler(psycopg.Error,database_error)

    def actor(request:Request):
        auth=request.headers.get('authorization','')
        if not auth.startswith('Bearer '):raise HTTPException(401,'Войдите в приложение.')
        key=hashlib.sha256(auth[7:].encode()).hexdigest()
        with store.transaction() as c:
            u=c.execute('SELECT u.id,u.username,u.name,u.job,u.role,u.active FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1',(key,time.time())).fetchone()
        if not u:raise HTTPException(401,'Сессия завершена. Войдите снова.')
        return dict(u)

    @app.get('/health')
    def health():return {'ok':True,'version':'1.4','ai_enabled':settings.ai_enabled,'features':['admin_chat']}
    @app.get('/',response_class=HTMLResponse)
    def home():return '<html><meta charset="utf-8"><title>НарядAI</title><h1>Сервер НарядAI работает</h1><p>Откройте start_client.bat в папке приложения.</p></html>'

    @app.post('/api/login')
    def login(body:LoginBody,request:Request):
        addr=request.client.host if request.client else 'local';clock=time.monotonic()
        with login_lock:
            recent=[t for t in attempts.get(addr,[]) if clock-t<60]
            if len(recent)>=20:raise HTTPException(429,'Слишком много попыток. Подождите минуту.')
            attempts[addr]=recent+[clock]
            if len(attempts)>1000:attempts.clear()
        user=store.authenticate(body.username,body.password,body.role)
        token=secrets.token_urlsafe(32)
        with store.transaction() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],time.time()+12*3600))
        return {'user':user,'token':token}

    @app.post('/api/logout')
    def logout(request:Request,user=Depends(actor)):
        key=hashlib.sha256(request.headers['authorization'][7:].encode()).hexdigest()
        with store.transaction() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(key,))
        return {'ok':True}

    @app.get('/api/snapshot')
    def snapshot(day:str='',user=Depends(actor)):
        day=day or date.today().isoformat();date.fromisoformat(day)
        # Согласованный снимок: мутации не вклиниваются между чтением нарядов и отчётов.
        with rpc_lock:
            if remote:jobs.expire()
            tasks=store.tasks(user);reports=store.reports(user);people=store.users(user)
            workers=[p for p in people if p['role']=='worker' and (user['role']!='worker' or p['id']==user['id'])]
            shifts={str(p['id']):store.shift(user,p['id'],day) for p in workers}
            free={str(p['id']):store.free_slots(user,p['id'],day) for p in workers}
            statuses={str(p['id']):store.employee_status(user,p['id']) for p in workers}
        return {'tasks':tasks,'reports':reports,'users':people,'day':day,'shifts':shifts,'free_slots':free,'employee_status':statuses,
                'ai_enabled':settings.ai_enabled,'server_time':time.time()}

    @app.get('/api/chat')
    def chat_history(conversation_id:str='',user=Depends(actor)):
        with rpc_lock:return chat.history(user,conversation_id)

    @app.post('/api/chat')
    def chat_send(body:ChatSend,user=Depends(actor)):
        with rpc_lock:return chat.send(user,body.conversation_id,body.request_id,body.message)

    @app.post('/api/chat/new')
    def chat_new(body:NewChat,user=Depends(actor)):
        with rpc_lock:return chat.new(user,body.request_id)

    @app.post('/api/call/{method}')
    def call(method:str,body:CallBody,user=Depends(actor)):
        if method not in WRITE_METHODS|READ_METHODS:raise HTTPException(404,'Неизвестная операция.')
        kwargs=body.kwargs.copy()
        if 'actor' in kwargs or 'photo_sources' in kwargs:raise ValueError('Недопустимые параметры запроса.')
        if body.photos and method!='submit':raise ValueError('Фото можно передавать только с отчётом.')
        with rpc_lock:
            with store.transaction() as c:
                previous=c.execute('SELECT * FROM rpc_results WHERE request_id=?',(body.request_id,)).fetchone()
            if previous:
                if previous['user_id']!=user['id'] or previous['method']!=method:raise PermissionError('Запрос принадлежит другому пользователю.')
                return {'result':json.loads(previous['result'])}
            with tempfile.TemporaryDirectory(prefix='naryadai-report-') as folder:
                if method=='submit':
                    sources=[]
                    for i,photo in enumerate(body.photos):
                        if not isinstance(photo,dict) or not isinstance(photo.get('content'),str):raise ValueError('Некорректное фото.')
                        ext=Path(str(photo.get('name',''))).suffix.lower()
                        if ext not in ('.jpg','.jpeg','.png','.webp'):raise ValueError('Фото: JPG, PNG или WebP.')
                        try:raw=base64.b64decode(photo['content'],validate=True)
                        except (ValueError,TypeError):raise ValueError('Не удалось прочитать фото.')
                        if len(raw)>8*1024*1024:raise ValueError('Фото должно быть не больше 8 МБ.')
                        path=Path(folder)/f'{i}{ext}';path.write_bytes(raw);sources.append(str(path))
                    kwargs['photo_sources']=sources
                fn=getattr(store,method)
                try:bound=inspect.signature(fn).bind(user,*body.args,**kwargs)
                except TypeError:raise ValueError('Неверные параметры операции.') from None
                try:result=fn(user,*body.args,**kwargs)
                except (TypeError,KeyError,AttributeError):raise ValueError('Проверьте значения в запросе.') from None
                if method in WRITE_METHODS:
                    with store.transaction() as c:
                        c.execute('INSERT INTO rpc_results VALUES(?,?,?,?,?)',(body.request_id,user['id'],method,json.dumps(result,ensure_ascii=False),str(time.time())))
                        if method=='reset_password':c.execute('DELETE FROM sessions WHERE user_id=?',(bound.arguments['uid'],))
                return {'result':result}

    @app.get('/api/photos/{name}')
    def photo(name:str,user=Depends(actor)):
        if Path(name).name!=name:raise HTTPException(404,'Фото не найдено.')
        if not any(name in r['photos'] for r in store.reports(user)):raise HTTPException(403,'Фото другого сотрудника.')
        try:raw=store.read_photo(name)
        except FileNotFoundError:raise HTTPException(404,'Фото не найдено.')
        return Response(raw,media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')

    def machine(request:Request):
        if not remote:raise HTTPException(404,'Удалённый обработчик не настроен.')
        provided=request.headers.get('authorization','').removeprefix('Bearer ')
        if not hmac.compare_digest(provided,settings.worker_token):raise HTTPException(401,'Неверный ключ обработчика ИИ.')

    @app.post('/api/ai/heartbeat')
    def heartbeat(worker=Depends(machine)):
        with rpc_lock:jobs.heartbeat()
        return {'ok':True}

    @app.post('/api/ai/claim')
    def claim_ai(worker=Depends(machine)):
        with rpc_lock:return {'job':jobs.claim()}

    @app.post('/api/ai/chat/claim')
    def claim_chat(worker=Depends(machine)):
        with rpc_lock:
            jobs.heartbeat()
            return {'job':chat.claim()}

    @app.post('/api/ai/chat/result/{rid}')
    def chat_result(rid:str,body:ChatResult,worker=Depends(machine)):
        with rpc_lock:
            chat.result(rid,body.lease,body.answer,body.error,body.model);jobs.heartbeat()
        return {'ok':True}

    @app.post('/api/ai/result/{rid}')
    def ai_result(rid:int,body:ResultBody,worker=Depends(machine)):
        result=parse_verdict(json.dumps(body.result,ensure_ascii=False)) if body.result is not None else None
        error='' if result else body.error or 'Модель не смогла обработать отчёт.'
        with rpc_lock:jobs.result(rid,body.lease,result,error,body.model)
        return {'ok':True}

    @app.get('/api/ai/photo/{rid}/{name}')
    def ai_photo(rid:int,name:str,request:Request,worker=Depends(machine)):
        if Path(name).name!=name:raise HTTPException(404,'Фото не найдено.')
        with rpc_lock:
            with store.transaction() as c:
                jobs.require_lease(c,rid,request.headers.get('x-job-lease',''))
                row=c.execute('SELECT photos FROM reports WHERE id=?',(rid,)).fetchone()
                if not row or name not in json.loads(row['photos']):raise HTTPException(403,'Фото другого отчёта.')
        return Response(store.read_photo(name),media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    return app
