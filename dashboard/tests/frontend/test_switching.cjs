// Slow and out-of-order responses must not block navigation or restore an old account.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../../frontend/js/core/app.js','utf8');
const functions=source.slice(source.indexOf('function cancelRecordLoads(){'),source.indexOf('function feedback('));
const pump=source.slice(source.indexOf('async function getRecord('),source.indexOf('function refreshWatchlist('));
const elements=new Map(),pending=[],main={inert:false};
const el=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false});return elements.get(id);};
const ctx={window:{},URL,Promise,AbortController,encodeURIComponent,surfaceNames:['home','watchlist','portfolio','macro','whales'],surface:'watchlist',currentUser:{id:'self',name:'Liam'},surfaceAccounts:{watchlist:'self',portfolio:'other'},viewedUserId:'self',accountStateVersion:0,accountRequest:null,recordGeneration:0,recordRequests:new Set(),queue:[],running:0,fetchingTickers:new Set(),tickers:['AAPL'],holdings:[],records:new Map(),readOnly:false,initialLoading:false,sortKey:null,cellValues:new Map(),cellFlashes:new Map(),stateWrites:Promise.resolve(),el,
 location:{href:'https://example.com/?surface=watchlist'},history:{state:null,replaceState(_state,_title,url){ctx.location.href=new URL(url,ctx.location.href).href;}},
 document:{querySelector:selector=>selector==='main'?main:el(selector),querySelectorAll:()=>[],body:{classList:{toggle(){}}}},
 rememberSurfaceAccount(name,id){ctx.surfaceAccounts[name]=id;},accountViewURL:(name,id)=>`/?surface=${name}&user=${id}`,feedback(){},render(){},scheduleRender(){},
 trackedTickers:()=>[...new Set([...ctx.tickers,...ctx.holdings.map(p=>p.ticker)])],FinFeedMacro:{open(){}},FinFeedWhales:{open(){}},FinFeedHome:{open(){}},
 // Intentionally ignore abort: also verify protection when stale responses arrive anyway.
 seedQuoteSnapshots(){},FinFeedAuth:{request:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))}};
ctx.FinFeedCache={read:()=>null,write(){},market:async(url,consume,{signal}={})=>{const response=await ctx.FinFeedAuth.request(url,{signal});if(!response.ok)throw new Error('request failed');const value=await response.json();consume(value);return value;}};
vm.createContext(ctx);vm.runInContext(functions+pump,ctx);
const flush=()=>new Promise(setImmediate);
const response=data=>({ok:true,json:async()=>data});
(async()=>{
 ctx.load(['AAPL'],true);assert.equal(ctx.running,1);
 const oldQuote=pending.at(-1);
 const first=ctx.changeViewedAccount('watchlist','first');await flush();
 assert.equal(main.inert,false);assert.equal(el('view-account').disabled,false);assert.equal(oldQuote.options.signal.aborted,true);
 const firstState=pending.at(-1);
 await ctx.switchSurface('portfolio'); // Must complete before the new account state responds.
 assert.equal(ctx.surface,'portfolio');assert.equal(el('portfolio-surface').hidden,false);await flush();
 assert.equal(firstState.options.signal.aborted,true);
 const newestState=pending.at(-1);
 await ctx.switchSurface('macro');assert.equal(ctx.surface,'macro');assert.equal(main.inert,false);
 newestState.resolve(response({state:{watchlist:['AAPL','MSFT'],positions:[]},readOnly:true,quotes:{}}));await flush();
 assert.deepEqual(Array.from(ctx.tickers),['AAPL','MSFT']);assert.equal(ctx.surface,'macro');
 assert.equal(new URL(ctx.location.href).searchParams.get('surface'),'macro');
 firstState.resolve(response({state:{watchlist:['WRONG'],positions:[]},readOnly:false,quotes:{}}));await first;
 assert.deepEqual(Array.from(ctx.tickers),['AAPL','MSFT']);assert.equal(ctx.readOnly,true);
 const newAapl=pending.filter(p=>p.url.startsWith('/api/security/AAPL?')).at(-1);
 newAapl.resolve(response({ticker:'AAPL',name:'new account'}));await flush();
 const newQuote=pending.find(p=>p.url.startsWith('/api/security/MSFT?'));
 newQuote.resolve(response({ticker:'MSFT',name:'new'}));await flush();
 oldQuote.resolve(response({ticker:'AAPL',name:'stale'}));await flush();
 assert.equal(ctx.records.get('AAPL').name,'new account');assert.equal(ctx.records.get('MSFT').name,'new');assert.equal(ctx.running,0);
 console.log('PASS: navigation and account selection stay interactive; cancelled and late responses cannot overwrite newer data');
})().catch(error=>{console.error(error);process.exitCode=1;});
