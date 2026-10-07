const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map(),context={window:{},navigator:{},Date,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}};
vm.runInNewContext(fs.readFileSync(__dirname+'/public/cache.js','utf8'),context);
const cache=context.window.FinFeedCache,key='macro-jobs';
const fresh={retrieved_at:'2026-10-07T03:00:00Z',metrics:[{latest:{value:29}}]};
assert(cache.write(key,fresh));const original=storage.get('finfeed-market:v1:'+key);
for(const value of [{...fresh,retrieved_at:'2026-10-07T02:00:00Z'},{...fresh,refreshing:true},{...fresh,partial:true},{...fresh,stale:true},{...fresh,errors:['offline']}]){
 assert.equal(cache.write(key,value),false);assert.equal(storage.get('finfeed-market:v1:'+key),original,'failed or older writes must not replace or extend successful snapshot');
}
assert(cache.write(key,{...fresh,retrieved_at:'2026-10-07T04:00:00Z'}));
console.log('PASS: older, partial, refreshing, stale and failed responses cannot replace or extend good cache');
