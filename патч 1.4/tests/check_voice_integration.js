/* Actual report-form integration with fake ASR and mocked HTTP API. No real microphone or AI. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
let chromium;
try { ({chromium} = require('playwright')); }
catch (_) { ({chromium} = require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))); }

const project = path.resolve(__dirname, '..');
const calls = [];
const responses = [];
const task = {id:77,title:'Проверка креплений',equipment:'Учебный насос',equipment_id:2,site:'Учебный участок',status:'inProgress',kind:'Плановая',duration:1,worker_id:101};
const fakeSpeech = () => {
  window.sessions = [];
  class FakeRecognition {
    constructor() { window.sessions.push(this); this.aborted = false; }
    start() { this.onstart?.(); }
    stop() { this.onend?.(); }
    abort() { this.aborted = true; this.onend?.(); }
    result(text) { this.onresult?.({resultIndex:0,results:[Object.assign([{transcript:text}], {isFinal:true})]}); }
  }
  window.SpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = undefined;
};

(async () => {
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    if (pathname.startsWith('/api/')) {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        const isSubmit = pathname === '/api/call/submit';
        if (isSubmit) calls.push(JSON.parse(body));
        const status = isSubmit ? responses.shift() || 400 : 200;
        res.writeHead(status, {'Content-Type':'application/json; charset=utf-8'});
        res.end(JSON.stringify(status >= 400 ? {detail:'Учебная ошибка отправки'} : {result:{},items:[]}));
      });
      return;
    }
    const relative = pathname === '/' ? 'web/index.html' : pathname === '/sw.js' ? 'web/sw.js' : decodeURIComponent(pathname).replace(/^\/+/, '');
    const filename = path.resolve(project, relative);
    if (!filename.startsWith(project + path.sep) || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) {
      res.writeHead(404); res.end('Not found'); return;
    }
    const types = {'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webmanifest':'application/manifest+json'};
    res.writeHead(200, {'Content-Type':types[path.extname(filename)] || 'application/octet-stream'});
    res.end(fs.readFileSync(filename));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless:true,...(process.env.NARYADAI_TEST_BROWSER ? {executablePath:process.env.NARYADAI_TEST_BROWSER} : {})});
    const context = await browser.newContext({viewport:{width:360,height:800},serviceWorkers:'block'});
    const page = await context.newPage();
    await page.addInitScript(fakeSpeech);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const bootstrap = async (seed = null) => {
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.waitForFunction(() => Boolean(window.NaryadVoice) && Boolean(document.querySelector('#login-form')));
      await page.evaluate(async ({task, seed}) => {
        window.testTask = task;
        state.token = 'fixture-session';
        state.user = {id:101,role:'worker',name:'Учебный сотрудник'};
        state.snapshot = {tasks:[task],reports:[],users:[state.user]};
        state.refs = {defect_codes:[{id:1,code:'D-01',name:'Ослабление крепления'}],materials:[]};
        state.busy = false;
        // Keep actual request/rpc/form/draft functions; isolate unrelated full-dashboard polling.
        refresh = async () => {};
        await clearDrafts();
        if (seed) await draftWrite(draftKey(task.id), seed);
        await openReportForm(task);
      }, {task, seed});
      await page.waitForSelector('#report-form');
    };
    const start = async (field = 'work') => {
      await page.locator(`.voice-trigger[aria-label="${field === 'work' ? 'Диктовать выполненные работы' : 'Диктовать результат проверки'}"]`).click();
      await page.locator('.voice-consent input').check();
      await page.locator('.voice-start').click();
    };

    await bootstrap();
    await start();
    await page.evaluate(() => sessions[0].result('Проверены крепления учебного насоса.'));
    await page.locator('.voice-stop').click();
    await page.locator('.voice-preview').fill('Подтянуты крепления учебного насоса.');
    if (process.env.NARYADAI_VOICE_SCREENSHOT) {
      fs.mkdirSync(path.dirname(process.env.NARYADAI_VOICE_SCREENSHOT), {recursive:true});
      await page.locator('.voice-panel').scrollIntoViewIfNeeded();
      await page.screenshot({path:process.env.NARYADAI_VOICE_SCREENSHOT,fullPage:true});
    }
    await page.locator('.voice-apply').click();
    await page.waitForFunction(async () => (await draftGet(draftKey(testTask.id)))?.work === 'Подтянуты крепления учебного насоса.');
    assert.equal(await page.locator('#work').inputValue(), 'Подтянуты крепления учебного насоса.');
    await page.locator('#close-dialog').click();
    await page.waitForFunction(() => reportVoice === null && !document.querySelector('#dialog').open);
    await page.evaluate(() => openReportForm(testTask));
    assert.equal(await page.locator('#work').inputValue(), 'Подтянуты крепления учебного насоса.', 'Actual IndexedDB draft survives close and reopen');
    console.log('PASS: actual report form applies reviewed dictation, saves IndexedDB draft and restores it');

    await bootstrap();
    const beforeBlocked = calls.length;
    await start();
    await page.evaluate(() => sessions[0].result('Текст ещё не подтверждён.'));
    assert.equal(await page.evaluate(() => document.querySelector('#report-form').checkValidity()), false);
    await page.locator('#submit-report').click();
    assert.match(await page.locator('#form-error').textContent(), /Добавьте распознанный текст/);
    assert.equal(calls.length, beforeBlocked);
    assert.equal(await page.locator('#work').inputValue(), '', 'Recording does not fill required report fields');
    await page.locator('.voice-stop').click();
    await page.locator('#submit-report').click();
    assert.match(await page.locator('#form-error').textContent(), /Добавьте распознанный текст/);
    assert.equal(calls.length, beforeBlocked);
    console.log('PASS: active and unapplied dictation block send before native required-field validation');

    const frozen = {
      work:'Зафиксированные выполненные работы.',result:'Контрольная проверка пройдена.',defect:'D-01 · Ослабление крепления',hours:1,materials:[],photos:[],
      pending:{request_id:'fixture-frozen-request',args:[77],kwargs:{work:'Зафиксированные выполненные работы.',result:'Контрольная проверка пройдена.',defect:'D-01 · Ослабление крепления',hours:1,materials:[]},photos:[]}
    };
    await bootstrap(frozen);
    assert.equal(await page.locator('#work').isDisabled(), true);
    assert.equal(await page.locator('.voice-trigger').first().isDisabled(), true);
    await page.evaluate(() => {
      document.querySelector('#work').value = 'Попытка заменить зафиксированный текст';
      document.querySelector('.voice-trigger').click();
    });
    assert.equal(await page.evaluate(() => sessions.length), 0);
    assert.equal(await page.locator('.voice-panel').isVisible(), false);
    const frozenStart = calls.length;
    responses.push(503, 400);
    await page.locator('#submit-report').click();
    await page.waitForFunction(() => !state.busy);
    assert.equal(await page.evaluate(() => Boolean(state.draft.pending)), true, 'Ambiguous server failure keeps exact retry payload');
    assert.equal(await page.locator('.voice-trigger').first().isDisabled(), true);
    await page.locator('#submit-report').click();
    await page.waitForFunction(() => !state.busy && !state.draft.pending);
    const expected = {args:frozen.pending.args,kwargs:frozen.pending.kwargs,photos:[],request_id:frozen.pending.request_id};
    assert.deepEqual(calls.slice(frozenStart), [expected, expected], 'Actual RPC retry preserves frozen arguments, photos and request identifier');
    assert.equal(await page.locator('#work').isDisabled(), false);
    assert.equal(await page.locator('.voice-trigger').first().isDisabled(), false, 'Cleared pending state refreshes dictation controls');
    await start();
    assert.equal(await page.evaluate(() => sessions.length), 1, 'Dictation works after frozen report is unfrozen');
    await page.locator('.voice-cancel').click();
    console.log('PASS: restored pending payload cannot be changed by dictation; retry stays identical and 4xx unfreezes controls');

    await bootstrap();
    await start();
    await page.evaluate(() => { sessions[0].result('Неприменённый текст перед закрытием'); window.closeLate = sessions[0].onresult; });
    await page.locator('#close-dialog').click();
    await page.waitForFunction(() => reportVoice === null);
    assert.equal(await page.evaluate(() => sessions[0].aborted), true);
    await page.evaluate(() => openReportForm(testTask));
    await page.evaluate(() => closeLate({resultIndex:0,results:[Object.assign([{transcript:'Поздний результат закрытой формы'}],{isFinal:true})]}));
    assert.equal(await page.locator('#work').inputValue(), '');
    await start();
    await page.evaluate(() => { window.replaceLate = sessions[1].onresult; });
    await page.evaluate(() => openReportForm({...testTask,id:78}));
    assert.equal(await page.evaluate(() => sessions[1].aborted), true);
    await page.evaluate(() => replaceLate({resultIndex:0,results:[Object.assign([{transcript:'Поздний результат заменённой формы'}],{isFinal:true})]}));
    assert.equal(await page.locator('#work').inputValue(), '');
    await start();
    await page.evaluate(() => { window.logoutLate = sessions[2].onresult; });
    await page.evaluate(() => endSession(false));
    assert.equal(await page.evaluate(() => sessions[2].aborted), true);
    await page.evaluate(() => logoutLate({resultIndex:0,results:[Object.assign([{transcript:'Поздний результат после выхода'}],{isFinal:true})]}));
    assert.equal(await page.evaluate(() => state.user), null);
    assert.equal(await page.locator('.voice-panel').count(), 0);
    assert.equal(await page.locator('#work').inputValue(), '');
    assert.deepEqual(errors, []);
    console.log('PASS: actual close, form replacement and logout abort recording and reject late callbacks');
    console.log('PASS: report voice integration has no uncaught browser errors; no real audio recognition was used');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
