'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const elements=new Map(),queue=[],animations=[];
function element(id){
  if(!elements.has(id))elements.set(id,{
    hidden:false,value:'',textContent:'',disabled:false,inert:false,listeners:{},
    addEventListener(type,fn){this.listeners[type]=fn;},
    getBoundingClientRect(){return {height:this.hidden?0:160};},
    animate(frames,options){const animation={frames,options,finished:Promise.resolve(),cancel(){this.cancelled=true;}};animations.push(animation);return animation;}
  });
  return elements.get(id);
}
const data=verified=>({verified,email:verified?'test@example.com':'',preferences:{enabled:true,jobs:true,treasury_threshold:5.1}});
const context={document:{getElementById:element},window:{matchMedia:()=>({matches:false})},FinFeedAuth:{request:()=>new Promise(resolve=>queue.push((value,ok=true)=>resolve({ok,json:async()=>value})))},setInterval:()=>1,clearInterval(){},Date};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/js/components/notifications.js'),'utf8'),context);
const ui=context.window.FinFeedNotifications;
(async()=>{
  const first=ui.open();
  assert.equal(element('notification-content').hidden,true);
  assert.equal(element('notification-loading').hidden,false);
  queue.shift()(data(true));await first;
  assert.equal(element('notification-binding-fields').hidden,true);
  assert.equal(element('notification-loading').hidden,true);
  assert.equal(element('notification-content').hidden,false);
  assert.equal(element('notification-save').disabled,true);
  assert.equal(element('notification-save').textContent,'提醒已设置');
  // A slower previous open cannot replace the latest account settings.
  const old=ui.open(),fresh=ui.open();
  const resolveOld=queue.shift(),resolveFresh=queue.shift();
  resolveFresh(data(false));await fresh;resolveOld(data(true));await old;
  assert.equal(element('notification-binding-fields').hidden,false);
  element('notification-code').value='123456';
  const verify=element('notification-verify').listeners.click();
  queue.shift()(data(true));await verify;
  assert.equal(element('notification-binding-fields').hidden,true);
  assert.equal(animations.at(-1).options.duration,520);
  assert.equal(animations.at(-1).frames[1].height,'0px');
  const unbind=element('notification-unbind').listeners.click({currentTarget:element('notification-unbind')});
  queue.shift()({});
  await new Promise(resolve=>setImmediate(resolve));
  queue.shift()(data(false));await unbind;
  assert.equal(element('notification-binding-fields').hidden,false);
  assert.equal(element('notification-binding-fields').inert,false);
  assert.equal(animations.at(-1).frames[0].height,'0px');
  const saveButton=element('notification-save');
  assert.equal(saveButton.disabled,true);
  element('notification-threshold').value='5.2';element('notification-threshold').listeners.input();
  const save=saveButton.listeners.click();
  assert.equal(saveButton.textContent,'保存中…');assert.equal(saveButton.disabled,true);
  const saved=data(false);saved.preferences.treasury_threshold=5.2;queue.shift()(saved);await save;
  assert.equal(saveButton.textContent,'提醒已设置');assert.equal(saveButton.disabled,true);
  await saveButton.listeners.click();assert.equal(queue.length,0);
  element('notification-threshold').value='5.1';element('notification-threshold').listeners.input();
  element('notification-news').checked=true;element('notification-news').listeners.change();
  assert.equal(saveButton.textContent,'保存提醒设置');assert.equal(saveButton.disabled,false);
  const failed=saveButton.listeners.click();queue.shift()({error:'保存失败'},false);await failed;
  assert.equal(saveButton.disabled,false);assert.equal(saveButton.textContent,'保存提醒设置');
  const pending=saveButton.listeners.click();
  element('notification-threshold').value='5.2';element('notification-threshold').listeners.input();
  const accepted=data(false);accepted.preferences.news=true;
  queue.shift()(accepted);await pending;
  assert.equal(element('notification-threshold').value,'5.2');
  assert.equal(saveButton.disabled,false); // Newer edits still need saving.
  const finalSave=saveButton.listeners.click();accepted.preferences.treasury_threshold=5.2;
  queue.shift()(accepted);await finalSave;
  assert.equal(saveButton.textContent,'提醒已设置');assert.equal(saveButton.disabled,true);
  element('notification-threshold').value='5.3';element('notification-threshold').listeners.input();
  assert.equal(saveButton.disabled,false);
  console.log('PASS: notification loading, binding transitions, save confirmation, retry and in-flight edits.');
})().catch(error=>{console.error(error);process.exitCode=1;});
