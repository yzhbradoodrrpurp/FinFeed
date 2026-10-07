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
 now+=29*60*1000;timer();assert.equal(requests,1,'must not refresh early');
 now+=60*1000;document.hidden=true;timer();assert.equal(requests,1,'background pause');
 document.hidden=false;get('news-surface').hidden=true;events.visibilitychange();assert.equal(requests,1,'other surface pause');
 get('news-surface').hidden=false;events.focus();await new Promise(r=>setImmediate(r));assert.equal(requests,2,'resume overdue refresh');
 timer();assert.equal(requests,2,'avoid duplicate refresh');
 console.log('PASS: 30-minute refresh, hidden page/surface pause, overdue resume, no duplicate refresh');
})();
