// Verify startup ordering with slow independent requests, without real credentials.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../../frontend/js/core/app.js','utf8');
const helpers=source.slice(source.indexOf('let accountRetryTimer='),source.indexOf('function cancelRecordLoads(){'));
const init=source.slice(source.indexOf('async function initializeState(){'),source.indexOf('\ninitializeState();'));
const pending=new Map(),calls=[],elements=new Map(),main={inert:false};
const el=id=>{if(!elements.has(id))elements.set(id,{disabled:false,hidden:false});return elements.get(id);};
const deferred=url=>new Promise(resolve=>pending.set(url,resolve));
const context={window:{},URLSearchParams,Promise,AbortController,clearTimeout,setTimeout,accountStateVersion:0,accountRequest:null,location:{search:'',hostname:'finfeed-research.vercel.app'},surface:'portfolio',currentUser:null,surfaceAccounts:{},viewedUserId:null,records:new Map(),initialLoading:true,readOnly:false,tickers:[],holdings:[],
 document:{addEventListener(){},querySelector:()=>main,querySelectorAll:()=>[],body:{classList:{toggle(){}}}},el,sessionStorage:{getItem:()=>null},escapeHTML:s=>s,switchSurface(){},rememberSurfaceAccount(name,id){context.surfaceAccounts[name]=id;},
 seedQuoteSnapshots(){},FinFeedNews:{initialize:()=>calls.push('news'),setWatchlist(){}},FinFeedAuth:{initialize:()=>deferred('auth'),request:deferred},FinFeedHome:{prefetch:()=>calls.push('home'),open:()=>calls.push('greeting')},FinFeedMacro:{open:()=>calls.push('macro')},FinFeedWhales:{open:()=>calls.push('whales')},
 trackedTickers:()=>[...new Set([...context.tickers,...context.holdings.map(p=>p.ticker)])],render:()=>calls.push('render'),load:tickers=>calls.push([...tickers]),setTimeout:callback=>{context.timers.push(callback);},timers:[],setInterval(){},refreshWatchlist(){},feedback:message=>calls.push(message)};
context.groupIds=['security','price'];context.ownGroupOrder=['price','security'];
const orderFunction=source.slice(source.indexOf('function applyAccountGroupOrder('),source.indexOf('const allColumns='));
vm.createContext(context);vm.runInContext(orderFunction+helpers+init,context);
(async()=>{
 const done=context.initializeState();assert.deepEqual(calls,[]);
 assert.equal(main.inert,true);assert.equal(context.readOnly,true); // Dashboard waits for authentication.
 pending.get('auth')({user:{id:'self',name:'Liam'}});await new Promise(setImmediate);
 assert.deepEqual(calls,['']);assert.equal(pending.size,3);assert.equal(main.inert,false);
 pending.get('/api/state')({ok:true,json:async()=>({state:{watchlist:['AAPL'],positions:[{ticker:'AAPL'},{ticker:'MSFT'}]},quotes:{},readOnly:false})});
 await new Promise(setImmediate);
 assert.deepEqual(calls.at(-1),['AAPL','MSFT']);assert.equal(main.inert,false);
 assert(!calls.includes('news'));context.timers.splice(0).forEach(run=>run());
 assert(calls.includes('news'));
 assert.equal(el('view-account').disabled,true); // Directory is still pending.
 pending.get('/api/accounts')({ok:true,json:async()=>({accounts:[{id:'self',name:'Liam'}]})});await done;
 assert.equal(el('view-account').disabled,false);
 // A failed initial auth check must recover without reloading or duplicating startup.
 calls.length=0;context.currentUser=null;
 const enabled={disabled:false,closest:()=>null},alreadyDisabled={disabled:true,closest:()=>null};
 context.document.querySelectorAll=()=>[enabled,alreadyDisabled];
 let retry;
 context.setTimeout=(callback,delay)=>{assert.equal(delay,15000);retry=callback;};
 context.FinFeedAuth.initialize=async()=>{throw new Error('API 请求超过 30 秒');};
 await context.initializeState();
 assert.equal(el('startup-status').hidden,false);assert.equal(enabled.disabled,true);
 assert(!calls.includes('home'));assert(!calls.includes('macro'));assert(!calls.includes('whales'));
 context.FinFeedAuth.initialize=()=>deferred('auth');
 retry();assert.equal(enabled.disabled,false);assert.equal(alreadyDisabled.disabled,true);
 // An overlapping startup invocation must not issue a second auth check.
 await context.initializeState();
 pending.get('auth')({user:{id:'self',name:'Liam'}});await new Promise(setImmediate);
 assert.equal(el('startup-status').hidden,true);
 assert(!calls.includes('home'));
 context.setTimeout=callback=>context.timers.push(callback);
 pending.get('/api/state')({ok:true,json:async()=>({state:{watchlist:['AAPL'],positions:[]},quotes:{},readOnly:false})});
 pending.get('/api/accounts')({ok:true,json:async()=>({accounts:[{id:'self',name:'Liam'}]})});
 await new Promise(setImmediate);
 context.timers.splice(0).forEach(run=>run());
 for(const name of ['home','news','macro','whales'])assert.equal(calls.filter(call=>call===name).length,1);
 assert.deepEqual(context.tickers,['AAPL']);assert.equal(context.initializeState.running,false);
 context.setTimeout=()=>{throw new Error('Redirect must not schedule a retry');};
 context.FinFeedAuth.initialize=async()=>{const error=new Error('expired');error.code='AUTH_REDIRECT';throw error;};
 await context.initializeState();assert.equal(main.inert,true);
 console.log('PASS: private snapshots render before shared views; private rows do not wait for account directory; only one account loads');
 console.log('PASS: failed auth automatically retries and starts each view once after recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
