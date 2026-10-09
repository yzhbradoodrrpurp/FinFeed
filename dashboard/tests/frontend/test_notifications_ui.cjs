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
const context={document:{getElementById:element},window:{matchMedia:()=>({matches:false})},FinFeedAuth:{request:()=>new Promise(resolve=>queue.push(value=>resolve({ok:true,json:async()=>value})))},setInterval:()=>1,clearInterval(){},Date};
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
  console.log('Notification loading, stale responses, binding collapse and unbinding expansion passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
