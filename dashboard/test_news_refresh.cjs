const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 let now=1000,requests=0,timer;
 const elements=new Map(),events={};
 const get=id=>{if(!elements.has(id))elements.set(id,{hidden:false,innerHTML:'',textContent:'',addEventListener(){},querySelectorAll:()=>[]});return elements.get(id);};
 const document={hidden:false,getElementById:get,querySelectorAll:()=>[],addEventListener:(key,callback)=>events[key]=callback};
 const window={addEventListener:(key,callback)=>events[key]=callback};
 const sandbox={window,document,Date:class extends Date{static now(){return now;}},Intl,AbortController,DOMException,setTimeout,clearTimeout,setInterval:callback=>timer=callback,FinFeedAuth:{request:async()=>{requests++;return{ok:true,json:async()=>({tickers:[]})};}}};
 vm.runInNewContext(fs.readFileSync('dashboard/public/news.js','utf8'),sandbox);
 await window.FinFeedNews.open();assert.equal(requests,1);
 now+=59*60*1000;timer();assert.equal(requests,1,'must not refresh early');
 now+=60*1000;document.hidden=true;get('news-surface').hidden=true;timer();await new Promise(r=>setImmediate(r));assert.equal(requests,2,'refresh on hidden page and other surface');
 now+=60*60*1000;document.hidden=false;events.visibilitychange();await new Promise(r=>setImmediate(r));assert.equal(requests,3,'refresh while another surface is selected');
 get('news-surface').hidden=false;events.focus();await new Promise(r=>setImmediate(r));assert.equal(requests,3,'already refreshed');
 timer();assert.equal(requests,3,'avoid duplicate refresh');
 console.log('PASS: hourly refresh, hidden page/surface refresh, overdue resume, no duplicate refresh');
})();
