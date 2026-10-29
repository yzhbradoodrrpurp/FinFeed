const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const saved=new Map(),requests=[];
const ctx={window:{},navigator:{},Date,Promise,AbortController,DOMException,TextDecoder,Uint8Array,setTimeout,clearTimeout,
 localStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},
 FinFeedAuth:{request:async url=>{requests.push(url);return {status:304,ok:false,headers:{get:()=> '1234'}};}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/core/cache.js','utf8'),ctx);
(async()=>{
 const cache=ctx.window.FinFeedCache;await cache.ready;
 const full={cache_version:'v1',fetched_at:new Date().toISOString(),metrics:{price:{value:100},revenue_q0:{value:123,basis:'quarter',inputs:{raw:123}}},quarter_0:'2026-09-30'};
 cache.write('request:/api/security/AAPL',full);
 const seen=[];await cache.market('/api/security/AAPL',v=>seen.push(v));
 assert.equal(requests[0],'/api/security/AAPL?version=v1');
 assert.equal(seen[0].metrics.revenue_q0.inputs.raw,123,'full cache appears before response');
 assert.equal(seen.at(-1).server_checked_at,1234);
 assert.equal(cache.read('request:/api/security/AAPL').data.metrics.revenue_q0.basis,'quarter');
 ctx.localStorage.getItem=()=>{throw Error('storage blocked');};ctx.localStorage.setItem=()=>{throw Error('quota');};
 assert.equal(cache.write('new',full),true,'memory/IndexedDB path survives localStorage failure');
 assert.equal(cache.read('new').data.metrics.price.value,100);
 console.log('PASS: unchanged snapshot reuses complete cache, refreshes checked time, and survives localStorage denial');
})().catch(e=>{console.error(e);process.exitCode=1;});
