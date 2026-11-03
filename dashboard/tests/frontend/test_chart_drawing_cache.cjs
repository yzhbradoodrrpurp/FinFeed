'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../frontend/js/views/candles.js'),'utf8');
const helpers=source.slice(source.indexOf('  const drawingMemory='),source.indexOf("  const svgNS="));
const disk=new Map();
const storage={getItem:key=>disk.get(key)||null,setItem:(key,value)=>disk.set(key,value)};
function client(localStorage=storage){
 const context={localStorage,indexedDB:undefined,setTimeout,Map,Promise,JSON,Number};
 vm.runInNewContext(helpers+'\nglobalThis.cache={read:readDrawingCache,write:writeDrawingCache};',context);
 return context.cache;
}
const snapshot=revision=>({revision,cache_version:String(revision).padStart(64,'a'),adjustment:'ForwardAdjust',lines:[{id:'a'.repeat(32),points:[{time:'2026-01-02',price:10},{time:'2026-02-02',price:12}]}]});
(async()=>{
 const cache=client(),account={userId:'account-one',symbol:'AAPL'};
 assert.equal(await cache.read(account.userId,account.symbol),null);
 const confirmed=snapshot(2);cache.write(account,confirmed);confirmed.lines[0].points[0].price=999;
 assert.equal((await cache.read(account.userId,account.symbol)).lines[0].points[0].price,10);
 assert.equal(await cache.read('account-two','AAPL'),null);
 assert.equal(await cache.read('account-one','MSFT'),null);
 cache.write(account,snapshot(1));
 assert.equal((await cache.read(account.userId,account.symbol)).revision,2);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal((await client().read(account.userId,account.symbol)).revision,2);
 const corrupted={...snapshot(3),lines:[null]};
 disk.set('finfeed-private-drawing:'+JSON.stringify(['corrupt','AAPL']),JSON.stringify(corrupted));
 assert.equal(await cache.read('corrupt','AAPL'),null);
 const denied=client({getItem(){throw Error('storage unavailable')},setItem(){throw Error('storage unavailable')}});
 denied.write(account,snapshot(4));
 assert.equal((await denied.read(account.userId,account.symbol)).revision,4);
 cache.write({userId:null,symbol:'AAPL'},snapshot(8));
 assert.equal(await cache.read(null,'AAPL'),null);
 console.log('PASS: private drawing cache survives reload, isolates accounts/symbols, clones confirmed data, rejects older/corrupt data and tolerates storage denial');
})().catch(error=>{console.error(error);process.exitCode=1});
