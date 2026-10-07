/* Render the real web client with deterministic API fixtures. No live server, AI or microphone. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
let chromium;
try { ({chromium} = require('playwright')); }
catch (_) { ({chromium} = require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))); }

const project = path.resolve(__dirname, '..');
const baseline = process.env.NARYADAI_UI_BASELINE === '1';
const screenshots = process.env.NARYADAI_UI_SCREENSHOTS;
const mode = {snapshotFailure:false,snapshotDelay:0,mutationFailure:false,mutationDelay:0,photoFailure:false,photoDelay:0,loginFailure:false,loginDelay:0};
const calls = [];
const users = [
  {id:101,role:'worker',name:'Данияр Садыков',username:'worker',job:'Слесарь-ремонтник',active:1},
  {id:102,role:'worker',name:'Алексей Волков',username:'worker2',job:'Электромонтёр',active:1},
  {id:201,role:'master',name:'Ирина Кузнецова',username:'master',job:'Мастер ремонтной смены',active:1},
  {id:301,role:'admin',name:'Администратор проекта',username:'admin',job:'Системный администратор',active:1},
];
const tasks = [
  {id:77,title:'Проверить крепления приводного насоса',description:'Проверить крепления и состояние соединений. Указать выполненные работы и результат контрольной проверки.',equipment:'Насос подачи воды Н-04',equipment_id:2,site:'Учебный участок дробления',site_id:1,status:'planned',priority:'high',kind:'Плановая',duration:1,worker_id:101,worker_name:'Данияр Садыков',start:9,deadline:'2099-10-08T12:00:00+05:00'},
  {id:78,title:'Заменить повреждённое уплотнение',description:'Установить уплотнение и проверить герметичность.',equipment:'Насос подачи воды Н-05',equipment_id:3,site:'Учебный участок дробления',site_id:1,status:'queued',priority:'normal',kind:'Плановая',duration:1.5,worker_id:101,worker_name:'Данияр Садыков',start:11,deadline:'2099-10-08T16:00:00+05:00'},
  {id:79,title:'Проверить датчик конвейера',description:'Проверить соединение датчика.',equipment:'Конвейер К-12',equipment_id:4,site:'Учебный участок транспортировки',site_id:2,status:'submitted',priority:'urgent',kind:'Внеплановая',duration:1,worker_id:102,worker_name:'Алексей Волков',start:8,deadline:'2099-10-08T11:00:00+05:00'},
];
const reports = [{id:501,task_id:79,title:tasks[2].title,equipment:tasks[2].equipment,worker_id:102,worker_name:users[1].name,status:'submitted',created:'2099-10-08T10:15:00+05:00',hours:0.8,work:'Проверено соединение датчика, восстановлено крепление.',result:'Сигнал датчика стабилен при контрольном запуске.',defect:'D-01 · Ослабление крепления',materials:[],photos:[],ai:{status:'completed',score:86,summary:'Проверка описана; решение остаётся за мастером.',checks:[],findings:[]}}];
const catalogs = {
  sites:[{id:1,name:'Учебный участок дробления',code:'DEMO-01',active:1},{id:2,name:'Учебный участок транспортировки',code:'DEMO-02',active:1}],
  equipment:tasks.map(task=>({id:task.equipment_id,name:task.equipment,site_id:task.site_id,inventory_number:'DEMO-'+task.equipment_id,equipment_type:'Насос',active:1})),
  brigades:[{id:1,name:'Учебная ремонтная бригада',active:1}],
  defect_codes:[{id:1,code:'D-01',name:'Ослабление крепления',active:1}],
  materials:[{id:1,name:'Уплотнение',unit:'шт',active:1}],
  work_norms:[{id:1,equipment_type:'Насос',kind:'Плановая',hours:1,description:'Осмотреть крепления насоса.',active:1}],
};
const fixture = () => ({tasks:tasks.map(task=>({...task,day:new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Qyzylorda'})})),reports,users,employee_status:{101:'queued',102:'free'},shifts:{101:{start:8,end:18},102:{start:8,end:18}},free_slots:{101:[[13,18]],102:[[10,18]]},notifications:[],metrics:[{id:101,done:12,score:89},{id:102,done:9,score:86}],ai_enabled:true,server_time:Date.now()/1000});

const responseFor = pathname => {
  if (pathname === '/api/login') return {token:'fixture-token',user:users[0]};
  if (pathname === '/api/snapshot') return fixture();
  if (pathname === '/api/catalogs') return catalogs;
  if (pathname === '/api/call/events') return {result:[{message:'Наряд назначен сотруднику',name:users[2].name,created:'2099-10-08T08:00:00+05:00'}]};
  if (pathname === '/api/chat') return {conversation_id:'fixture-chat',messages:[],pending:false,ai_enabled:true,online:true};
  if (pathname === '/api/chat/conversations' || pathname === '/api/knowledge') return {items:[]};
  if (pathname === '/api/admin/monitor') return {database:'SQLite · учебная',counts:{tasks:3,reports:1},worker_online:true,ai_enabled:true,web_enabled:false,events:[],chat_jobs:[],report_jobs:[]};
  if (pathname === '/api/call/report') return {result:reports[0]};
  if (pathname.startsWith('/api/call/')) return {result:[]};
  return {items:[],result:{}};
};

(async () => {
  const server = http.createServer((req,res) => {
    const pathname = new URL(req.url,'http://localhost').pathname;
    if (pathname.startsWith('/api/')) {
      let body=''; req.on('data',chunk=>body+=chunk);
      req.on('end',()=>{
        calls.push({pathname,method:req.method,body});
        if(pathname.startsWith('/api/photos/')){
          setTimeout(()=>{
            if(mode.photoFailure){res.writeHead(503);res.end('Fixture photo unavailable');}
            else {res.writeHead(200,{'Content-Type':'image/png'});res.end(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBYkAAAAASUVORK5CYII=','base64'));}
          },mode.photoDelay);return;
        }
        const mutation=pathname==='/api/call/transition';
        const failure=pathname==='/api/snapshot'&&mode.snapshotFailure||mutation&&mode.mutationFailure||pathname==='/api/login'&&mode.loginFailure;
        const delay=pathname==='/api/snapshot'?mode.snapshotDelay:mutation?mode.mutationDelay:pathname==='/api/login'?mode.loginDelay:0;
        setTimeout(()=>{
          res.writeHead(failure?503:200,{'Content-Type':'application/json; charset=utf-8'});
          res.end(JSON.stringify(failure?{detail:'Учебный сервер временно недоступен. Повторите действие.'}:responseFor(pathname)));
        },delay);
      });return;
    }
    const relative=pathname==='/'?'web/index.html':pathname==='/sw.js'?'web/sw.js':decodeURIComponent(pathname).replace(/^\/+/, '');
    const filename=path.resolve(project,relative);
    if(!filename.startsWith(project+path.sep)||!fs.existsSync(filename)||!fs.statSync(filename).isFile()){res.writeHead(404);res.end('Not found');return;}
    const types={'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webmanifest':'application/manifest+json'};
    res.writeHead(200,{'Content-Type':types[path.extname(filename)]||'application/octet-stream'});res.end(fs.readFileSync(filename));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  const findings=[];
  try {
    browser=await chromium.launch({headless:true,...(process.env.NARYADAI_TEST_BROWSER?{executablePath:process.env.NARYADAI_TEST_BROWSER}:{})});
    const context=await browser.newContext({viewport:{width:360,height:800},serviceWorkers:'block'});
    const page=await context.newPage();
    await page.addInitScript(()=>{window.SpeechRecognition=class{start(){throw new Error('UI fixture must never record audio');}};window.webkitSpeechRecognition=undefined;});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const start=async role=>{
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.waitForSelector('#login-form');
      await geometry(`login ${page.viewportSize().width}`);
      await page.evaluate(user=>{state.token='fixture-token';state.user=user;state.page='home';renderShell();refresh(true);},users.find(user=>user.role===role));
      await page.waitForSelector('#sync-time');
    };
    const capture=async (name,fullPage=true)=>{if(screenshots){
      await page.waitForFunction(()=>document.getAnimations().every(animation=>animation.playState!=='running'||animation.effect?.getComputedTiming().iterations===Infinity));
      fs.mkdirSync(screenshots,{recursive:true});await page.screenshot({path:path.join(screenshots,name+'.png'),fullPage});
    }};
    const geometry=async label=>{
      const measurements=await page.evaluate(()=>{
        const output=[];
        const viewport=document.documentElement.clientWidth;
        if(document.documentElement.scrollWidth>viewport+1)output.push(`document overflow ${document.documentElement.scrollWidth-viewport}px`);
        const dialog=document.querySelector('#dialog');
        if(dialog.open&&dialog.scrollWidth>dialog.clientWidth+1)output.push(`dialog overflow ${dialog.scrollWidth-dialog.clientWidth}px`);
        for(const svg of document.querySelectorAll('button > svg.icon')){
          const button=svg.parentElement;
          if(!svg.getClientRects().length||button.closest('.mobile-nav'))continue;
          const image=svg.getBoundingClientRect(),control=button.getBoundingClientRect();
          const vertical=Math.abs(image.y+image.height/2-control.y-control.height/2);
          const text=button.textContent.trim();
          const horizontal=Math.abs(image.x+image.width/2-control.x-control.width/2);
          if(vertical>1.6)output.push(`${button.id||text||button.getAttribute('aria-label')} icon vertical offset ${vertical.toFixed(1)}px`);
          if(!text&&horizontal>1.6)output.push(`${button.id||button.getAttribute('aria-label')} icon horizontal offset ${horizontal.toFixed(1)}px`);
          if(image.x<control.x-1||image.right>control.right+1||image.y<control.y-1||image.bottom>control.bottom+1)output.push(`${button.id||text} icon outside button`);
        }
        return output;
      });
      if(measurements.length) findings.push({label,issues:measurements});
      if(!baseline)assert.deepEqual(measurements,[],label);
    };
    for(const width of [320,360,768,1280,1440]){
      await page.setViewportSize({width,height:900});
      for(const role of ['worker','master','admin']){
        await start(role);
        await geometry(`${role} home ${width}`);
        if(width===360||width===1280)await capture(`${baseline?'before':'after'}-${role}-${width}-home`);
        if(width===360)await capture(`${baseline?'before':'after'}-${role}-360-home-viewport`,false);
        const pages=role==='worker'?['tasks','schedule','reports','settings']:role==='master'?['tasks','people','more','chat','analytics']:['equipment','people','more','console','knowledge','analytics'];
        for(const target of pages){
          await page.evaluate(target=>go(target),target);
          if(target==='chat')await page.waitForSelector('.chat-welcome');
          if(target==='console')await page.waitForFunction(()=>document.querySelector('#monitor-cards')?.children.length>0);
          await geometry(`${role} ${target} ${width}`);
        }
        if(role==='worker'){
          await page.evaluate(()=>openTask(77));
          await geometry(`worker task sheet ${width}`);
          await page.locator('#close-dialog').click();
          await page.evaluate(()=>openReportForm({...state.snapshot.tasks[0],status:'inProgress'}));
          await geometry(`worker report form ${width}`);
          await page.locator('.voice-trigger').first().click();
          await page.waitForSelector('.voice-panel:not([hidden])');
          await geometry(`worker voice preview ${width}`);
          await page.locator('#close-dialog').click();
        }
        if(role==='master'){
          await page.evaluate(()=>createTask());
          await geometry(`master create form ${width}`);
          if(width===360)await capture(`${baseline?'before':'after'}-master-360-create`);
          await page.locator('#task-details summary').focus();
          await page.keyboard.press('Enter');
          assert.equal(await page.locator('#task-details').evaluate(node=>node.open),true,'Disclosure remains keyboard-operable');
          await geometry(`master expanded create form ${width}`);
          await page.locator('#close-dialog').click();
          await page.evaluate(()=>openReport(501));
          await geometry(`master review form ${width}`);
          if(width===360)await capture(`${baseline?'before':'after'}-master-360-review`);
          await page.locator('#close-dialog').click();
        }
        if(role==='admin'&&width>=768){
          await page.setViewportSize({width,height:600});
          const issue=await page.evaluate(()=>{
            const sidebar=document.querySelector('.sidebar').getBoundingClientRect();
            const logout=document.querySelector('#side-logout').getBoundingClientRect();
            return logout.bottom>sidebar.bottom+1?`Logout extends ${(logout.bottom-sidebar.bottom).toFixed(1)}px below sidebar`:'';
          });
          if(issue)findings.push({label:`admin sidebar ${width}x600`,issues:[issue]});
          if(!baseline)assert.equal(issue,'',`Admin navigation and logout remain inside the ${width}x600 viewport`);
          await page.setViewportSize({width,height:900});
        }
      }
    }
    await page.setViewportSize({width:360,height:800});await start('worker');
    await page.evaluate(()=>openTask(77));
    await geometry('worker task sheet 360');
    await capture(`${baseline?'before':'after'}-worker-360-task`);
    await page.locator('#close-dialog').click();
    await page.evaluate(()=>openReportForm({...state.snapshot.tasks[0],status:'inProgress'}));
    await geometry('worker report form 360');
    await capture(`${baseline?'before':'after'}-worker-360-report`);
    await page.locator('#close-dialog').click();
    if(!baseline){
      const names=await page.evaluate(()=>navItems().map(([key])=>key).concat(['chat','console','knowledge','more','analytics']));
      const missing=await page.evaluate(names=>names.filter(name=>!paths[name]),names);
      assert.deepEqual(missing,[],'Every navigation entry has its semantic icon');
      console.log('PASS: real worker/master/admin views and create/review forms have no overflow and centered icons at 320/360/768/1280/1440px');

      mode.loginDelay=700;mode.loginFailure=true;
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.waitForSelector('#login-form');
      await page.locator('#username').fill('fixture-worker');await page.locator('#password').fill('fixture-password');
      const login=page.locator('#login-form button[type=submit]');
      const loginBox=await login.boundingBox();
      await login.click();
      assert.equal(await login.getAttribute('aria-busy'),'true','Login announces its actual pending request');
      const pendingBox=await login.boundingBox();
      assert.equal(pendingBox.width,loginBox.width,'Loading indicator does not change the login button width');
      await page.waitForFunction(()=>Boolean(document.querySelector('#login-error')?.textContent));
      assert.equal(await login.isDisabled(),false,'Failed login can be retried manually');
      assert.equal(await page.locator('#login-error').getAttribute('role'),'alert');
      await capture('after-360-login-error');
      mode.loginFailure=false;mode.loginDelay=0;

      mode.snapshotDelay=700;
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.waitForSelector('#login-form');
      await page.evaluate(user=>{state.token='fixture-token';state.user=user;state.page='home';renderShell();refresh(true);},users[0]);
      await page.waitForSelector('.skeleton');
      assert.equal(await page.locator('.skeleton').first().isVisible(),true,'First load has a visible loading placeholder');
      await capture('after-360-loading');
      await page.emulateMedia({reducedMotion:'reduce'});
      assert.equal(await page.locator('.skeleton').first().evaluate(node=>getComputedStyle(node).animationName),'none','System reduced motion disables loading shimmer');
      await page.waitForSelector('#sync-time');
      mode.snapshotDelay=0;
      await page.emulateMedia({reducedMotion:'no-preference'});

      mode.snapshotFailure=true;
      await page.evaluate(()=>refresh(true));
      await page.waitForSelector('#retry-load');
      assert.match(await page.locator('#main [role=alert]').textContent(),/временно недоступен/);
      await capture('after-360-connection-error');
      mode.snapshotFailure=false;await page.locator('#retry-load').click();
      await page.waitForSelector('#sync-time');
      assert.equal(await page.locator('#retry-load').count(),0,'Manual reconnect recovers from load error');

      await page.evaluate(()=>openTask(77));
      mode.mutationDelay=700;mode.mutationFailure=true;
      const previous=calls.filter(call=>call.pathname==='/api/call/transition').length;
      await page.locator('#primary-task').click();
      assert.equal(await page.locator('#primary-task').isDisabled(),true,'Action is disabled while the exact request is pending');
      const busy=await page.locator('#primary-task').getAttribute('aria-busy');
      assert.equal(busy,'true','Busy action announces its pending state');
      await page.waitForFunction(()=>!state.busy);
      assert.equal(await page.locator('#primary-task').isDisabled(),false,'A failed action is available for a deliberate retry');
      assert.equal(await page.locator('#dialog').evaluate(node=>node.open),true,'Failed operation keeps task context open');
      assert.match(await page.locator('#form-error').textContent(),/временно недоступен/);
      assert.equal(await page.locator('#form-error').getAttribute('role'),'alert');
      assert.equal(await page.locator('#primary-task').getAttribute('aria-busy'),null,'Busy attribute clears after failure');
      assert.equal(calls.filter(call=>call.pathname==='/api/call/transition').length,previous+1,'Failure is not automatically retried');
      await capture('after-360-action-error');
      const firstAttempt=calls.filter(call=>call.pathname==='/api/call/transition').at(-1);
      await page.locator('#primary-task').click();
      await page.waitForFunction(()=>!state.busy);
      const retried=calls.filter(call=>call.pathname==='/api/call/transition').at(-1);
      assert.equal(retried.body,firstAttempt.body,'Deliberate retry preserves the exact request identity and arguments');
      assert.equal(calls.filter(call=>call.pathname==='/api/call/transition').length,previous+2,'Only the second user action causes the retry');
      mode.mutationDelay=0;mode.mutationFailure=false;
      await page.locator('#primary-task').click();
      await page.waitForFunction(()=>!state.busy&&!document.querySelector('#dialog').open);
      assert.match(await page.locator('#toast').textContent(),/Изменения сохранены/,'Successful operation confirms its result');
      assert.equal(calls.filter(call=>call.pathname==='/api/call/transition').length,previous+3);
      mode.photoDelay=700;mode.photoFailure=true;
      await page.evaluate(()=>{state.snapshot.reports[0].photos=['fixture-photo.png'];openReport(501);});
      await page.waitForSelector('.ui-photo-loading');
      assert.equal(await page.locator('.photo-tile .spinner').isVisible(),true,'Delayed photo visibly announces its loading state');
      await page.waitForSelector('.photo-tile .ui-error');
      assert.match(await page.locator('.photo-tile span.ui-error').textContent(),/Фото недоступно/);
      assert.equal(await page.locator('.ui-photo-loading').count(),0,'Failed photo exits loading state');
      await geometry('failed photo review 360');
      await page.locator('#close-dialog').click();
      mode.photoDelay=0;mode.photoFailure=false;
      await page.evaluate(()=>go('settings'));
      await page.locator('#reduce-motion').check();
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('reduce-motion')),true);
      await page.evaluate(()=>toast('Работа сохранена'));
      const running=await page.locator('#toast').evaluate(node=>getComputedStyle(node).animationName);
      assert.equal(running,'none','In-app reduced motion also disables feedback entrance');
      console.log('PASS: visible loading, reduced-motion support, failed connection recovery and deliberate action retry states');
    }
    assert.deepEqual(errors,[],'Rendering and real client interactions produce no uncaught errors');
    if(baseline)console.log(JSON.stringify({baselineFindings:findings},null,2));
    else console.log('PASS: UI polish has no uncaught browser errors; fixtures used no real AI, audio or database');
  } finally {
    if(browser)await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
