// A transient failed response must not erase prices or portfolio valuation inputs.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/public/app.js','utf8');
const functions=source.slice(source.indexOf('async function getRecord('),source.indexOf('function refreshWatchlist('));
const pending=[];
const saved={ticker:'AAPL',name:'Apple',fetched_at:'2026-10-05T20:00:00Z',quote_date:'2026-10-05',currency:'USD',metrics:{price:{value:100},eps_q0:{value:2}},sources:{quote:'https://finance.yahoo.com/quote/AAPL/'}};
const ctx={AbortController,Date,Set,Promise,encodeURIComponent,records:new Map([['AAPL',saved]]),recordRequests:new Set(),recordGeneration:0,queue:[],running:0,fetchingTickers:new Set(),trackedTickers:()=>['AAPL'],scheduleRender(){},el:()=>({disabled:false}),FinFeedAuth:{request:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))}};
vm.createContext(ctx);vm.runInContext(functions,ctx);
const flush=()=>new Promise(setImmediate);
(async()=>{
 ctx.load(['AAPL'],true);pending.shift().reject(new Error('HTTP 503'));await flush();
 let record=ctx.records.get('AAPL');assert.equal(record.metrics.price.value,100);assert.equal(record.metrics.eps_q0.value,2);assert.equal(record.fetched_at,saved.fetched_at);assert.equal(record.stale,true);
 ctx.load(['AAPL'],true);pending.shift().resolve({ok:true,json:async()=>({ticker:'AAPL',metrics:{},errors:['offline']})});await flush();
 assert.equal(ctx.records.get('AAPL').metrics.price.value,100);assert.equal(ctx.records.get('AAPL').stale,true);
 ctx.load(['AAPL'],true);pending.shift().resolve({ok:true,json:async()=>({...saved,metrics:{price:{value:110}}})});await flush();
 assert.equal(ctx.records.get('AAPL').metrics.price.value,110);assert.equal(ctx.records.get('AAPL').stale,undefined);assert.equal(ctx.running,0);
 assert.equal(saved.stale,undefined);
 console.log('PASS: network and empty-response failures preserve dated quote and financial snapshot; successful retry clears stale status');
})().catch(error=>{console.error(error);process.exitCode=1;});
