const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../../frontend/js/core/auth-client.js','utf8');
const calls=[],ctx={window:{},URL,Uint8Array,AbortController,DOMException,crypto:require('node:crypto').webcrypto,performance,location:{origin:'https://example.com',replace(){}},clearTimeout,
 setTimeout:(f,ms)=>ms<2000?setTimeout(f,0):setTimeout(f,ms),fetch:async(url)=>{
 calls.push(url);if(url.includes('client-failure'))return {ok:true};
 let attempt=calls.filter(x=>x===url).length;
 if(url==='/api/state'&&attempt===1)throw new TypeError('offline');
 if(url==='/api/state'&&attempt===2)return {ok:false,status:503};
 return {ok:url!=='/api/forbidden',status:url==='/api/forbidden'?403:200,json:async()=>({state:{watchlist:['AAPL']}})};
}};
vm.createContext(ctx);vm.runInContext(source,ctx);
(async()=>{
 const data=await ctx.window.FinFeedAuth.read('/api/state');assert.equal(data.state.watchlist[0],'AAPL');assert.equal(calls.filter(x=>x==='/api/state').length,3);
 await assert.rejects(ctx.window.FinFeedAuth.read('/api/forbidden'));assert.equal(calls.filter(x=>x==='/api/forbidden').length,1);
 let controller=new AbortController();controller.abort(new DOMException('cancel','AbortError'));
 ctx.fetch=async()=>{throw new DOMException('cancel','AbortError');};
 await assert.rejects(ctx.window.FinFeedAuth.read('/api/state',{signal:controller.signal}),e=>e.name==='AbortError');
 console.log('PASS: complete account reads retry transient failures; permission failures and cancellation do not retry');
})().catch(e=>{console.error(e);process.exitCode=1;});
