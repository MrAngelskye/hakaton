"""Один сервер приложения для всех клиентов. Запуск через run_server.py."""
import base64,hashlib,hmac,inspect,json,logging,mimetypes,secrets,sqlite3,tempfile,threading,time
from contextlib import asynccontextmanager
from datetime import date,timedelta
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException,Depends,Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response,JSONResponse,HTMLResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from server.store import ServerStore
from server.anythingllm import AnythingLLM,AIError,parse_verdict

LOG=logging.getLogger('naryadai')
MAX_BODY=60*1024*1024
WRITE_METHODS={'create_task','claim','reschedule','transition','submit','review','add_user','set_active','reset_password','support_update_task','set_shift','reassign_task','change_priority','catalog_upsert','set_material_norm','set_employee_profile','start_downtime','end_downtime','assess_refusal','confirm_repeat','acknowledge_notification','acknowledge_notifications','send_announcement'}
READ_METHODS={'task','events','pauses','shift','free_slots','employee_status','catalogs','photos_for_task','notifications','analytics','metrics','equipment_history','task_downtimes'}

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
    photos:list=Field(default_factory=list,max_length=5)

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
    settings.validate_case()
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
    from server.notifications import NotificationDispatcher
    notifications=NotificationDispatcher(store,settings)
    def deadline_loop():
        while not stopping.is_set():
            try:notifications.tick()
            except Exception:LOG.exception('Ошибка контроля сроков/доставки уведомлений')
            stopping.wait(5)

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
        scheduler=threading.Thread(target=deadline_loop,name='deadline-notifications',daemon=True)
        thread.start();scheduler.start()
        try:yield
        finally:stopping.set();thread.join(timeout=2);scheduler.join(timeout=2);store.close()

    app=FastAPI(title='НарядAI · сервер',version='1.5',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.provider=ai;app.state.chat=chat
    app.state.notifications=notifications
    app.add_middleware(GZipMiddleware,minimum_size=1000)

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
    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request,exc):return JSONResponse({'detail':'Запись нарушает целостность БД. Проверьте справочники и текущее состояние наряда.'},status_code=409)

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
    def health():return {'ok':True,'version':'1.5','release':'1.5-notifications.1','ai_enabled':settings.ai_enabled,'features':['admin_chat','case1_workflow','period_analytics','notifications','atomic_rpc','mobile_web','desktop_notifications','announcements']}
    web=Path(__file__).resolve().parents[1]/'web'
    app.mount('/web',StaticFiles(directory=web),name='web')
    app.mount('/assets/branding',StaticFiles(directory=web.parent/'assets'/'branding'),name='branding')
    @app.get('/')
    def home():return FileResponse(web/'index.html',media_type='text/html')
    @app.get('/sw.js')
    def service_worker():return FileResponse(web/'sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})
    @app.get('/manifest.webmanifest')
    def manifest():return FileResponse(web/'manifest.webmanifest',media_type='application/manifest+json')

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
    def snapshot(day:str='',history_days:int=Query(14,ge=0,le=366),limit:int=Query(500,ge=1,le=1000),user=Depends(actor)):
        day=day or date.today().isoformat();date.fromisoformat(day)
        # Согласованный снимок: мутации не вклиниваются между чтением нарядов и отчётов.
        with store.transaction() as c:
            if settings.database_url:c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            tasks=store.tasks(user,since=(date.today()-timedelta(days=history_days)).isoformat(),limit=limit+1)
            truncated=len(tasks)>limit;tasks=tasks[:limit]
            reports=store.reports(user,task_ids=[t['id'] for t in tasks]);people=store.users(user)
            workers=[p for p in people if p['role']=='worker' and (user['role']!='worker' or p['id']==user['id'])]
            shifts,free,statuses=store.availability(user,day,people=workers)
            metrics=store.metrics(user);inbox=store.notifications(user)
        return {'tasks':tasks,'reports':reports,'users':people,'day':day,'shifts':shifts,'free_slots':free,'employee_status':statuses,
                'metrics':metrics,'notifications':inbox,'history_days':history_days,'truncated':truncated,'ai_enabled':settings.ai_enabled,'server_time':time.time()}

    @app.get('/api/catalogs')
    def catalogs(user=Depends(actor)):return store.catalogs(user)

    @app.get('/api/tasks')
    def tasks_page(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500),user=Depends(actor)):
        with store.transaction():rows=store.tasks(user,limit=limit+1,offset=offset)
        return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}

    @app.get('/api/reports')
    def reports_page(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500),user=Depends(actor)):
        with store.transaction():rows=store.reports(user,limit=limit+1,offset=offset)
        return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}

    @app.get('/api/analytics')
    def analytics(start:str,end:str,site_id:int|None=None,equipment_id:int|None=None,worker_id:int|None=None,brigade_id:int|None=None,user=Depends(actor)):
        return store.analytics(user,start,end,site_id=site_id,equipment_id=equipment_id,worker_id=worker_id,brigade_id=brigade_id)

    @app.get('/api/notifications')
    def inbox(user=Depends(actor)):return {'items':store.notifications(user)}

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
        if method=='create_task' and user['role'] not in ('master','admin'):raise PermissionError('Выдавать наряды может мастер или администратор.')
        if method=='submit' and user['role'] not in ('worker','admin'):raise PermissionError('Отчёт отправляет назначенный исполнитель.')
        if 'actor' in kwargs or 'photo_sources' in kwargs:raise ValueError('Недопустимые параметры запроса.')
        if body.photos and method not in ('submit','create_task'):raise ValueError('Фото разрешены при выдаче наряда и отправке отчёта.')
        payload_hash=hashlib.sha256(json.dumps({'method':method,'args':body.args,'kwargs':body.kwargs,'photos':body.photos},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        # Decode, validate and upload before opening the write transaction.
        with tempfile.TemporaryDirectory(prefix='naryadai-report-') as folder:
            sources=[]
            for i,photo in enumerate(body.photos):
                if not isinstance(photo,dict) or not isinstance(photo.get('content'),str):raise ValueError('Некорректное фото.')
                ext=Path(str(photo.get('name',''))).suffix.lower()
                if ext not in ('.jpg','.jpeg','.png','.webp'):raise ValueError('Фото: JPG, PNG или WebP.')
                try:raw=base64.b64decode(photo['content'],validate=True)
                except (ValueError,TypeError):raise ValueError('Не удалось прочитать фото.')
                if len(raw)>8*1024*1024:raise ValueError('Фото должно быть не больше 8 МБ.')
                path=Path(folder)/f'{i}{ext}';path.write_bytes(raw);sources.append(str(path))
            if method in ('submit','create_task'):kwargs['photo_sources']=sources
            fn=getattr(store,method)
            try:bound=inspect.signature(fn).bind(user,*body.args,**kwargs)
            except TypeError:raise ValueError('Неверные параметры операции.') from None
            if method in WRITE_METHODS:
                # Check completed retries before uploading the same bytes again.
                with store.transaction() as c:previous=c.execute('SELECT * FROM rpc_results WHERE request_id=?',(body.request_id,)).fetchone()
                if previous:
                    if previous['user_id']!=user['id'] or previous['method']!=method:raise PermissionError('Запрос принадлежит другому пользователю.')
                    if previous['payload_hash']!=payload_hash:raise HTTPException(409,'request_id уже использован с другим содержанием.')
                    return {'result':json.loads(previous['result'])}
            with store.photo_batch(sources),store.transaction(write=method in WRITE_METHODS) as c:
                if method in WRITE_METHODS:
                    # Cross-process serialization + UNIQUE ID. Mutation, events, inbox and receipt commit together.
                    previous=c.execute('SELECT * FROM rpc_results WHERE request_id=?',(body.request_id,)).fetchone()
                    if previous:
                        if previous['user_id']!=user['id'] or previous['method']!=method:raise PermissionError('Запрос принадлежит другому пользователю.')
                        if previous['payload_hash']!=payload_hash:raise HTTPException(409,'request_id уже использован с другим содержанием.')
                        return {'result':json.loads(previous['result'])}
                try:result=fn(user,*body.args,**kwargs)
                except (TypeError,KeyError,AttributeError):raise ValueError('Проверьте значения в запросе.') from None
                if method in WRITE_METHODS:
                    c.execute('INSERT INTO rpc_results(request_id,user_id,method,result,created,payload_hash) VALUES(?,?,?,?,?,?)',(body.request_id,user['id'],method,json.dumps(result,ensure_ascii=False),str(time.time()),payload_hash))
                    if method=='reset_password':c.execute('DELETE FROM sessions WHERE user_id=?',(bound.arguments['uid'],))
                return {'result':result}

    @app.get('/api/photos/{name}')
    def photo(name:str,user=Depends(actor)):
        if Path(name).name!=name:raise HTTPException(404,'Фото не найдено.')
        if not store.can_read_photo(user,name):raise HTTPException(403,'Фото другого сотрудника.')
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
                row=c.execute('SELECT task_id,photos FROM reports WHERE id=?',(rid,)).fetchone()
                before=c.execute("SELECT 1 FROM task_photos WHERE task_id=? AND kind='before' AND object_key=?",(row['task_id'],name)).fetchone() if row else None
                if not row or name not in json.loads(row['photos']) and not before:raise HTTPException(403,'Фото другого отчёта.')
        return Response(store.read_photo(name),media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    return app
