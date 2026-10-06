// Verify startup ordering with slow independent requests, without real credentials.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/public/app.js','utf8');
const init=source.slice(source.indexOf('async function initializeState(){'),source.indexOf('\ninitializeState();'));
const pending=new Map(),calls=[],elements=new Map(),main={inert:false};
const el=id=>{if(!elements.has(id))elements.set(id,{disabled:false,hidden:false});return elements.get(id);};
const deferred=url=>new Promise(resolve=>pending.set(url,resolve));
const context={URLSearchParams,Promise,AbortController,accountStateVersion:0,accountRequest:null,location:{search:'',hostname:'finfeed-research.vercel.app'},surface:'portfolio',currentUser:null,surfaceAccounts:{},viewedUserId:null,records:new Map(),initialLoading:true,readOnly:false,tickers:[],holdings:[],
 document:{querySelector:()=>main,querySelectorAll:()=>[],body:{classList:{toggle(){}}}},el,sessionStorage:{getItem:()=>null},escapeHTML:s=>s,switchSurface(){},rememberSurfaceAccount(name,id){context.surfaceAccounts[name]=id;},
 FinFeedAuth:{initialize:()=>deferred('auth'),request:deferred},FinFeedHome:{prefetch:()=>calls.push('home'),open:()=>calls.push('greeting')},FinFeedMacro:{open:()=>calls.push('macro')},FinFeedWhales:{open:()=>calls.push('whales')},
 trackedTickers:()=>[...new Set([...context.tickers,...context.holdings.map(p=>p.ticker)])],render:()=>calls.push('render'),load:tickers=>calls.push([...tickers]),setInterval(){},refreshWatchlist(){},feedback:message=>calls.push(message)};
vm.createContext(context);vm.runInContext(init,context);
(async()=>{
 const done=context.initializeState();assert.deepEqual(calls,[]);
 pending.get('auth')({user:{id:'self',name:'Liam'}});await new Promise(setImmediate);
 assert.deepEqual(calls,['home','macro','whales']);assert.equal(pending.size,3);assert.equal(main.inert,false);
 pending.get('/api/state')({ok:true,json:async()=>({state:{watchlist:['AAPL'],positions:[{ticker:'AAPL'},{ticker:'MSFT'}]},quotes:{},readOnly:false})});
 await new Promise(setImmediate);
 assert.deepEqual(calls.at(-1),['AAPL','MSFT']);assert.equal(main.inert,false);
 assert.equal(el('view-account').disabled,true); // Directory is still pending.
 pending.get('/api/accounts')({ok:true,json:async()=>({accounts:[{id:'self',name:'Liam'}]})});await done;
 assert.equal(el('view-account').disabled,false);
 console.log('PASS: shared views start after auth; private rows do not wait for account directory; only one account loads');
})().catch(e=>{console.error(e);process.exitCode=1;});
