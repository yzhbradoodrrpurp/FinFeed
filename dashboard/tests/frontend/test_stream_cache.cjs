// Incremental rendering and cross-tab lease reuse, with actual NDJSON reader.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const saved=new Map(),locks=new Map();let calls=0,release,firstChunk;
const ready=new Promise(r=>firstChunk=r),gate=new Promise(r=>release=r);
const navigator={locks:{request:async(name,options,run)=>{
 const previous=locks.get(name)||Promise.resolve();let unlock;
 const next=new Promise(r=>unlock=r);locks.set(name,next);
 await previous;try{return await run();}finally{unlock();}
}}};
function tab(){const ctx={window:{},navigator,AbortController,DOMException,TextDecoder,Uint8Array,Date,setTimeout,clearTimeout,
 localStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},FinFeedAuth:{request:async()=>{calls++;let n=0;
 return {ok:true,headers:{get:()=> 'application/x-ndjson'},body:{getReader:()=>({
 read:async()=>{n++;if(n===1){firstChunk();return {value:new TextEncoder().encode('{"price":100,"partial":true}\n')};}
 if(n===2){await gate;return {value:new TextEncoder().encode('{"price":101,"refreshing":false}\n')};}return {done:true};},releaseLock(){}})}};}}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/core/cache.js','utf8'),ctx);return ctx.window.FinFeedCache;}
(async()=>{const a=tab(),b=tab(),first=[],second=[];
 const job=a.market('/api/security/QA?stream=1',v=>first.push(v));await ready;await new Promise(setImmediate);
 assert.equal(first[0].price,100);assert.equal(first[0].partial,true);
 const other=b.market('/api/security/QA?stream=1',v=>second.push(v));release();await Promise.all([job,other]);
 assert.equal(calls,1);assert.equal(second.at(-1).price,101);
 assert.equal(first.at(-1).price,101);console.log('PASS: quote stage renders before completion; two tabs share one completed request');
})().catch(e=>{console.error(e);process.exitCode=1;});
