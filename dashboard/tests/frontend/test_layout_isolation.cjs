'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('dashboard/frontend/js/core/app.js','utf8');
let subscriber,controls;const writes=[];
const ctx={currentUser:{id:'A'},viewedUserId:'A',readOnly:false,render(){},Promise,
 window:{FinFeedPreferences:{subscribe:fn=>subscriber=fn,save:patch=>{writes.push(patch);return Promise.resolve();}},FinFeedWatchlistOrder:{bind:options=>controls=options}}};
vm.createContext(ctx);
vm.runInContext("const groupIds=['security','price'];let groupOrder=[...groupIds],ownGroupOrder=[...groupIds];"+source.slice(source.indexOf('function canReorderWatchlistGroups('),source.indexOf('const allColumns='))+source.slice(source.lastIndexOf('window.FinFeedPreferences?.subscribe')),ctx);
const order=()=>Array.from(controls.getOrder());
(async()=>{
 subscriber({watchlistGroupOrder:['price','security']});assert.deepEqual(order(),['price','security']);
 ctx.viewedUserId='B';ctx.readOnly=true;ctx.applyAccountGroupOrder({uiPreferences:{watchlistGroupOrder:['security','price']}});
 assert.equal(controls.canReorder(),false);assert.deepEqual(order(),['security','price']);
 controls.reorder(['price','security']);assert.deepEqual(order(),['security','price']);
 await assert.rejects(controls.save(['price','security']),/只能修改自己的/);assert.equal(writes.length,0);
 // Owner preference refresh while viewing B must not override B's displayed order.
 subscriber({watchlistGroupOrder:['price','security']});assert.deepEqual(order(),['security','price']);
 ctx.viewedUserId='A';ctx.readOnly=false;ctx.applyAccountGroupOrder({});assert.deepEqual(order(),['price','security']);
 controls.reorder(['security','price']);await controls.save(controls.getOrder());assert.equal(writes.length,1);
 assert.deepEqual(Array.from(writes[0].watchlistGroupOrder),['security','price']);
 // Loading states are also read-only, even when the requested account is self.
 ctx.readOnly=true;await assert.rejects(controls.save(['price','security']));assert.equal(writes.length,1);
 console.log('PASS: foreign layouts are read-only, owner refreshes stay separate, blocked actions make no writes, own edits persist');
})().catch(error=>{console.error(error);process.exitCode=1;});
