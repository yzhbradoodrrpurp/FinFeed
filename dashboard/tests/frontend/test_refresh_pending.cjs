// A long provider job is rejoined, not forced again or reported as an error.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map(),urls=[],seen=[];
const ctx={window:{},navigator:{},AbortController,DOMException,TextDecoder,Uint8Array,Date,
 setTimeout:(fn,ms)=>setTimeout(fn,ms===1000?0:ms),clearTimeout,
 localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
 FinFeedAuth:{request:async url=>{
  urls.push(url);let sent=false;
  const value=urls.length===1?{price:100,pending:true,refreshing:true,stale:true}:{price:101,refreshing:false};
  return {ok:true,headers:{get:()=> 'application/x-ndjson'},body:{getReader:()=>({read:async()=>{
   if(sent)return {done:true};sent=true;return {value:new TextEncoder().encode(JSON.stringify(value)+'\n')};
  },releaseLock(){}})}};
 }}};
vm.runInNewContext(fs.readFileSync(__dirname+'/../../frontend/js/core/cache.js','utf8'),ctx);
(async()=>{
 await ctx.window.FinFeedCache.market('/api/home?symbol=A&stream=1&refresh=1',v=>seen.push(v),{refresh:true});
 assert.equal(urls.length,2);assert(!urls[1].includes('refresh=1'));
 assert.equal(seen.at(-1).price,101);assert(seen.every(v=>!v.errors));
 console.log('PASS: pending refresh rejoins the shared job and publishes final data without a duplicate force refresh');
})().catch(e=>{console.error(e);process.exitCode=1;});
