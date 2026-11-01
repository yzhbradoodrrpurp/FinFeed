// Failed or pending identity checks must never insert a local Watchlist row.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../../frontend/js/core/app.js','utf8');
const fragment=source.slice(source.indexOf('let addingTickers='),source.indexOf('function detail('));
const nodes=new Map(),shell={scrollTop:0};
const el=id=>{if(!nodes.has(id))nodes.set(id,{disabled:false,textContent:'',inert:false,querySelector:()=>el('submit'),querySelectorAll:()=>[],closest:()=>shell});return nodes.get(id);};
let resolve,reject,writes=0;
const ctx={el,window:{},readOnly:false,accountStateVersion:1,tickers:['AAPL'],watchlistFavorites:[],trackedTickers:()=>ctx.tickers,render(){},load(){},persistState:()=>{writes++;return new Promise((a,b)=>{resolve=a;reject=b;});}};
vm.createContext(ctx);vm.runInContext(fragment,ctx);
(async()=>{
 const pending=ctx.addTickers('MCX');assert.deepEqual(ctx.tickers,['AAPL']);assert.equal(el('watchlist').inert,true);
 reject(new Error('没有该 Ticker：MCX，无法添加'));await assert.rejects(pending,/没有该 Ticker/);
 assert.deepEqual(ctx.tickers,['AAPL']);assert.equal(el('watchlist').inert,false);
 const good=ctx.addTickers('MSFT');assert.deepEqual(ctx.tickers,['AAPL']);resolve({watchlist:['AAPL','MSFT']});await good;
 assert.deepEqual(ctx.tickers,['AAPL','MSFT']);
 await ctx.addTickers('MSFT');assert.equal(writes,2);
 const changed=ctx.addTickers('MU');ctx.accountStateVersion++;ctx.tickers=['GOOG'];resolve({watchlist:['AAPL','MSFT','MU']});
 assert.equal(await changed,null);assert.deepEqual(ctx.tickers,['GOOG']);
 const failedElsewhere=ctx.addTickers('MCX');ctx.accountStateVersion++;reject(new Error('late failure'));assert.equal(await failedElsewhere,null);
 console.log('PASS: verified admission is atomic; errors and late account responses do not insert local rows');
})();
