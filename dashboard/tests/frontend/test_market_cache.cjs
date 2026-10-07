const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const saved=new Map(),pending=new Map(),elements=new Map();
class Element{
 constructor(id){this.id=id;this.textContent='';this.hidden=false;this.notice=null;this.classList={toggle(){}};}
 set innerHTML(v){this.html=v;this.notice=null;for(const match of v.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element(match[1]));}
 get innerHTML(){return this.html||'';}addEventListener(){}setAttribute(){}
 querySelector(){return this.notice;}append(node){this.notice=node;}
}
for(const id of ['home-indices','home-market-status','home-countdown','home-countdown-label','home-session-time','home-update-status','home-refresh','home-surface','page-title','macro-grid','macro-fed','macro-refresh','macro-surface'])elements.set(id,new Element(id));
const context={window:{},navigator:{},AbortController,DOMException,setTimeout:()=>1,clearTimeout(){},TextDecoder,Uint8Array,document:{getElementById:id=>elements.get(id)||null,createElement:()=>new Element('notice'),addEventListener(){}},localStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},Date,Intl,performance:{now:()=>0},setInterval(){},FinFeedAuth:{request:url=>new Promise(resolve=>pending.set(url,data=>resolve({ok:true,json:async()=>data})))}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/core/cache.js','utf8'),context);context.FinFeedCache=context.window.FinFeedCache;
const timestamp=new Date().toISOString();
context.FinFeedCache.write('home-^GSPC',{index:{name:'S&P 500',label:'标普 500',price:100,source:'https://finance.yahoo.com/',quoted_at:timestamp},retrieved_at:timestamp});
context.FinFeedCache.write('macro-jobs',{metrics:[{label:'非农新增就业',unit:'千人',latest:{value:100,date:'2026-09-01'},source:'https://fred.stlouisfed.org/'}],retrieved_at:timestamp});
vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/views/home.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/views/macro.js','utf8'),context);
context.window.FinFeedHome.prefetch();context.window.FinFeedMacro.open();
assert(elements.get('home-index-0').innerHTML.includes('100.00'));
assert(elements.get('home-index-0').innerHTML.includes('缓存'));
assert(elements.get('macro-jobs').innerHTML.includes('100'));
assert(elements.get('macro-jobs').notice.textContent.includes('缓存'));
assert.equal(pending.size,9); // Calendar + 3 indices + 4 Macro cards + Fed.
pending.get('/api/home?symbol=%5EGSPC&stream=1')({index:{name:'S&P 500',label:'标普 500',price:105,source:'https://finance.yahoo.com/',quoted_at:timestamp},retrieved_at:timestamp});
pending.get('/api/macro/jobs?stream=1')({metrics:[],errors:['unavailable'],retrieved_at:timestamp});
setImmediate(()=>{
 assert(elements.get('home-index-0').innerHTML.includes('105.00'));
 assert(!elements.get('home-index-0').innerHTML.includes('缓存'));
 assert(elements.get('macro-jobs').innerHTML.includes('100'));
 assert(elements.get('macro-jobs').notice.textContent.includes('更新失败'));
 console.log('PASS: cached data appears before network completion; fresh items render independently; failed refresh retains labeled cache');
});
