/* Report dictation acceptance checks. Fake recognition; never opens a real microphone. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
let chromium;
try { ({chromium} = require('playwright')); }
catch (_) { ({chromium} = require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))); }

const source = fs.readFileSync(path.join(__dirname, '../web/voice.js'), 'utf8');
const fixture = `<!doctype html><html lang="ru"><head><meta charset="utf-8"></head><body>
<form id="report-form"><fieldset id="report-fields">
<label for="work">Что выполнено</label><textarea id="work" maxlength="10000"></textarea>
<label for="result">Результат проверки</label><textarea id="result" maxlength="10000"></textarea>
</fieldset><button id="send" type="submit">Отправить</button></form>
<script>
window.sessions=[];window.applied=0;window.inputs=0;window.submits=0;window.guard=true;
class FakeRecognition {
 constructor(){window.sessions.push(this);this.aborted=false;this.stopped=false;}
 start(){this.onstart?.();}
 stop(){this.stopped=true;this.onend?.();}
 abort(){this.aborted=true;this.onend?.();}
 result(parts,index=0){const results=parts.map(p=>Object.assign([{transcript:p.text}],{isFinal:p.final}));this.onresult?.({results,resultIndex:index});}
 fail(error){this.onerror?.({error});}
}
window.SpeechRecognition=FakeRecognition;
document.querySelector('form').addEventListener('input',()=>window.inputs++);
document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();window.submits++;});
</script><script src="/voice.js"></script><script>
window.voice=NaryadVoice.mount(document.querySelector('form'),{isCurrent:()=>window.guard,onApply:()=>window.applied++});
</script></body></html>`;

(async () => {
 const server=http.createServer((req,res)=>{
  res.writeHead(200,{'Content-Type':req.url==='/voice.js'?'application/javascript; charset=utf-8':'text/html; charset=utf-8'});
  res.end(req.url==='/voice.js'?source:fixture);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try {
  browser=await chromium.launch({headless:true,...(process.env.NARYADAI_TEST_BROWSER?{executablePath:process.env.NARYADAI_TEST_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:360,height:800}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const reload=()=>page.goto(`http://127.0.0.1:${server.address().port}/`);
  const open=async field=>{await page.locator(`.voice-trigger[aria-label="${field==='work'?'Диктовать выполненные работы':'Диктовать результат проверки'}"]`).click();};
  const start=async field=>{await open(field);await page.locator('.voice-consent input').check();await page.locator('.voice-start').click();};
  await reload();
  await page.locator('#work').fill('Уже записанная работа.');
  await open('work');
  assert.equal(await page.locator('.voice-start').isDisabled(),true,'Explicit consent precedes browser recognition');
  assert.equal(await page.evaluate(()=>sessions.length),0,'Opening panel never starts a microphone');
  await page.locator('.voice-consent input').check();await page.locator('.voice-start').click();
  await page.evaluate(()=>sessions[0].result([{text:'Проверены крепления',final:false}]));
  assert.equal(await page.locator('#work').inputValue(),'Уже записанная работа.','Interim recognition cannot edit report');
  await page.evaluate(()=>sessions[0].result([{text:'Проверены крепления.',final:true},{text:'Выполнен запуск',final:false}]));
  await page.evaluate(()=>sessions[0].result([{text:'Проверены крепления.',final:true},{text:'Выполнен запуск.',final:true}],1));
  await page.evaluate(()=>sessions[0].result([{text:'Проверены крепления.',final:true},{text:'Выполнен запуск.',final:true}],0));
  await page.locator('.voice-stop').click();
  assert.equal(await page.locator('.voice-preview').inputValue(),'Проверены крепления. Выполнен запуск.','Cumulative recognition is not duplicated');
  assert.equal(await page.evaluate(()=>voice.hasUnapplied()),true,'Unreviewed text is visible to submission guard');
  await page.locator('#work').fill('Ручная правка во время диктовки.');
  await page.locator('.voice-preview').fill('Исправленное название узла.');
  const inputCount=await page.evaluate(()=>inputs);
  await page.locator('.voice-apply').click();
  assert.equal(await page.locator('#work').inputValue(),'Ручная правка во время диктовки.\nИсправленное название узла.');
  assert.equal(await page.evaluate(()=>applied),1);
  assert.equal(await page.evaluate(()=>inputs),inputCount+1,'Applied voice text fires input to save report draft');
  assert.equal(await page.evaluate(()=>submits),0,'Dictation never submits a report');
  assert.equal(await page.evaluate(()=>voice.hasUnapplied()),false);
  console.log('PASS: consent, interim/final deduplication, manual correction, append and draft input event');

  await start('result');
  await page.evaluate(()=>sessions[1].result([{text:'<img src=x onerror=alert(1)>',final:true}]));
  await page.locator('.voice-stop').click();await page.locator('.voice-apply').click();
  assert.equal(await page.locator('#result').inputValue(),'<img src=x onerror=alert(1)>');
  assert.equal(await page.locator('.voice-panel img').count(),0,'Recognized text remains text');
  console.log('PASS: both report fields and literal recognized text');

  await reload();await start('work');
  await page.evaluate(()=>sessions[0].result([{text:'Подтверждённая часть',final:true},{text:'Исчезающий фрагмент',final:false}]));
  await page.evaluate(()=>sessions[0].result([{text:'Подтверждённая часть',final:true}],1));
  assert.equal(await page.locator('.voice-interim').textContent(),'','Removed provisional fragments disappear');
  await page.locator('.voice-stop').click();
  await page.locator('.voice-trigger[aria-label="Диктовать результат проверки"]').click();
  assert.match(await page.locator('.voice-status').textContent(),/Сначала добавьте/);
  assert.equal(await page.locator('.voice-preview').inputValue(),'Подтверждённая часть','Changing target does not discard review');
  await page.locator('.voice-cancel').click();
  assert.equal(await page.locator('#work').inputValue(),'');
  assert.equal(await page.evaluate(()=>voice.hasUnapplied()),false);
  console.log('PASS: disappearing interim results, explicit target change and cancellation');

  await reload();await start('work');
  await page.evaluate(()=>{sessions[0].result([{text:'Текст до сбоя',final:true}]);sessions[0].fail('network');});
  assert.match(await page.locator('.voice-status').textContent(),/Нет связи/);
  assert.equal(await page.locator('.voice-preview').inputValue(),'Текст до сбоя');
  await page.locator('.voice-apply').click();
  assert.equal(await page.locator('#work').inputValue(),'Текст до сбоя');
  await page.locator('.voice-start').click();await page.evaluate(()=>sessions[1].fail('not-allowed'));
  assert.match(await page.locator('.voice-status').textContent(),/Доступ к микрофону запрещён/);
  assert.equal(await page.locator('#work').isEditable(),true);
  console.log('PASS: network and permission errors preserve report and recognized text');

  await reload();await page.locator('#work').fill('x'.repeat(9998));await start('work');
  await page.evaluate(()=>sessions[0].result([{text:'Длинное дополнение',final:true}]));
  await page.locator('.voice-stop').click();await page.locator('.voice-apply').click();
  assert.equal((await page.locator('#work').inputValue()).length,9998,'Maxlength rejection does not truncate original');
  assert.match(await page.locator('.voice-status').textContent(),/недостаточно места/);
  assert.equal(await page.locator('.voice-preview').inputValue(),'Длинное дополнение');
  console.log('PASS: maximum length never silently truncates report');

  await reload();await start('work');
  await page.evaluate(()=>{window.oldResult=sessions[0].onresult;window.guard=false;oldResult({resultIndex:0,results:[Object.assign([{transcript:'Поздний текст'}],{isFinal:true})]});});
  assert.equal(await page.locator('#work').inputValue(),'');
  assert.equal(await page.evaluate(()=>sessions[0].aborted),true,'Expired form aborts recognition');
  await reload();await start('work');
  await page.evaluate(()=>{window.oldResult=sessions[0].onresult;voice.destroy();oldResult({resultIndex:0,results:[Object.assign([{transcript:'После закрытия'}],{isFinal:true})]});});
  assert.equal(await page.locator('.voice-panel').count(),0);
  assert.equal(await page.locator('#work').inputValue(),'');
  assert.equal(await page.evaluate(()=>sessions[0].aborted),true);
  console.log('PASS: stale form/session callbacks and teardown release recognition');

  await reload();await page.evaluate(()=>document.querySelector('#report-fields').disabled=true);
  await page.evaluate(()=>document.querySelector('.voice-trigger').click());
  assert.equal(await page.locator('.voice-panel').isVisible(),false);
  assert.equal(await page.evaluate(()=>sessions.length),0,'Frozen pending report cannot start dictation');
  await page.evaluate(()=>{document.querySelector('#report-fields').disabled=false;voice.destroy();window.SpeechRecognition=undefined;window.webkitSpeechRecognition=undefined;voice=NaryadVoice.mount(document.querySelector('form'));});
  await open('work');
  assert.match(await page.locator('.voice-status').textContent(),/голосовой ввод недоступен/);
  assert.equal(await page.locator('#work').isEditable(),true);
  assert.equal(await page.locator('.voice-start').isDisabled(),true);
  await reload();await page.evaluate(()=>{voice.destroy();guard=false;document.querySelector('#report-fields').disabled=true;voice=NaryadVoice.mount(document.querySelector('form'),{isCurrent:()=>guard});});
  assert.equal(await page.locator('.voice-trigger').first().isDisabled(),true);
  await page.evaluate(()=>{guard=true;document.querySelector('#report-fields').disabled=false;voice.refresh();});
  assert.equal(await page.locator('.voice-trigger').first().isDisabled(),false,'A rejected pending report can use dictation again');
  await reload();await start('work');
  await page.evaluate(()=>{sessions[0].result([{text:'Текст перед прерыванием',final:true}]);voice.interrupt();});
  assert.equal(await page.evaluate(()=>sessions[0].aborted),true);
  assert.equal(await page.locator('.voice-preview').inputValue(),'Текст перед прерыванием');
  await page.locator('.voice-apply').click();
  assert.equal(await page.locator('#work').inputValue(),'Текст перед прерыванием');
  console.log('PASS: interruption releases microphone and retains reviewed transcript');

  await reload();await page.clock.install();await start('work');
  await page.locator('.voice-stop').click();
  await page.locator('.voice-start').click();
  await page.clock.fastForward(6000);
  assert.equal(await page.evaluate(()=>voice.isBusy()),true,'Old synchronous stop leaves no timeout to cancel next session');
  await page.clock.fastForward(120000);
  assert.equal(await page.evaluate(()=>sessions[1].stopped),true,'A recording has a bounded duration');
  assert.equal(await page.evaluate(()=>voice.isBusy()),false);
  await page.locator('.voice-start').click();
  await page.evaluate(()=>sessions[2].stop=function(){this.stopped=true;});
  await page.locator('.voice-stop').click();await page.clock.fastForward(6000);
  assert.equal(await page.evaluate(()=>sessions[2].aborted),true,'Stuck stop releases recognition after bounded wait');
  assert.match(await page.locator('.voice-status').textContent(),/Ответ сервиса не получен/);
  console.log('PASS: synchronous stop race, recording limit and hung service watchdog');
  assert.deepEqual(errors,[]);
  console.log('PASS: pending report, unsupported browser and manual fallback; no browser errors');
 } finally { if(browser)await browser.close();await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);process.exitCode=1;});
