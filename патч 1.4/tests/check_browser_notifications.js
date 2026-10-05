/* Exercise the actual browser notifier with two tabs and a delayed service worker. */
const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'..','web','notifications.js'),'utf8');
const storage=new Map(),shown=[];let permission='granted',waiting;
const registration={active:true,showNotification:async(title,options)=>{shown.push({title,options});},getNotifications:async()=>[]};
let lock=Promise.resolve();
const locks={request:(_,fn)=>{const run=lock.then(fn);lock=run.catch(()=>{});return run;}};
function create(){const ctx={window:{isSecureContext:true},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},Notification:{get permission(){return permission},requestPermission:async()=>permission},navigator:{locks,serviceWorker:{getRegistration:async()=>waiting?await waiting:registration}},CustomEvent:class{}};ctx.window.Notification=ctx.Notification;vm.createContext(ctx);vm.runInContext(source,ctx);return ctx.window.NaryadNotifications;}
(async()=>{const user={id:7};const a=create(),b=create();const msg={id:2,title:'Срочный наряд',body:'НР-5',task_id:5,severity:'critical'};
 await a.feed([],user);await a.enable(user);shown.length=0;
 await Promise.all([a.feed([msg],user),b.feed([msg],user)]);assert.equal(shown.length,1,'Two tabs must not duplicate a notification');
 await a.feed([msg],user);assert.equal(shown.length,1);
 assert.equal(shown[0].options.data.taskId,5);assert.equal(shown[0].options.requireInteraction,true);
 const c=create();await c.feed([msg],user);assert.equal(shown.length,1,'Reconnect/reload must not repeat');
 await c.disable(user);await c.feed([{...msg,id:3}],user);assert.equal(shown.length,1,'Disabled account must receive inbox only');
 permission='denied';await assert.rejects(c.enable(user));assert.equal(shown.length,1);
 permission='granted';await c.feed([],user);await c.enable(user);shown.length=0;
 const many=Array.from({length:20},(_,i)=>({...msg,id:100+i,severity:i===0?'critical':'info'}));await c.feed(many,user);assert.equal(shown.length,2,'Backlog should be grouped');
 const d=create();await d.feed([],user);let release;waiting=new Promise(resolve=>release=resolve);const pending=d.feed([{...msg,id:999}],user);await new Promise(resolve=>setTimeout(resolve,0));
 const stopping=d.stop();release(registration);waiting=null;await Promise.all([pending,stopping]);assert.equal(shown.length,2,'Logout cancels delayed notification');
 console.log('PASS: actual browser notifier, two tabs, reload, disabled/denied permission, critical target, grouped backlog and logout race');
})().catch(error=>{console.error(error);process.exitCode=1});
