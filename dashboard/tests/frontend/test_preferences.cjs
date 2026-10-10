'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const queue=[],events={};let latest;
const context={window:{addEventListener:(name,fn)=>events[name]=fn},document:{addEventListener(){},getElementById:()=>({})},FinFeedAuth:{request:(url,options)=>new Promise(resolve=>queue.push({options,resolve:data=>resolve({ok:true,json:async()=>({preferences:data})})}))}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/js/core/preferences.js'),'utf8'),context);
const client=context.window.FinFeedPreferences,flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 client.subscribe(data=>latest=data);
 const load=client.initialize();queue.shift().resolve({watchlistGroupOrder:['price','security'],homeSectorOrder:['XLC','XLY']});await load;
 assert.equal(client.ready,true);assert.equal(latest.watchlistGroupOrder[0],'price');
 const stale=events.focus();
 const first=client.save({watchlistGroupOrder:['security','price']}),second=client.save({homeSectorOrder:['XLY','XLC']});await flush();
 assert.equal(queue.length,2);const refresh=queue.shift(),write=queue.shift();
 assert.deepEqual(JSON.parse(write.options.body),{watchlistGroupOrder:['security','price']});
 write.resolve({watchlistGroupOrder:['security','price']});await first;await flush();
 const next=queue.shift();assert.deepEqual(JSON.parse(next.options.body),{homeSectorOrder:['XLY','XLC']});next.resolve({homeSectorOrder:['XLY','XLC']});await second;
 refresh.resolve({watchlistGroupOrder:['price','security'],homeSectorOrder:['XLC','XLY']});await stale;
 assert.equal(latest.watchlistGroupOrder[0],'price'); // No stale response broadcast after completed writes.
 const reload=events.focus();queue.shift().resolve({watchlistGroupOrder:['security','price'],homeSectorOrder:['XLY','XLC']});await reload;
 assert.equal(latest.watchlistGroupOrder[0],'security');assert.equal(latest.homeSectorOrder[0],'XLY');
 console.log('PASS: account preferences load, serialize partial writes, reject stale refreshes and synchronize on focus');
})().catch(error=>{console.error(error);process.exitCode=1;});
