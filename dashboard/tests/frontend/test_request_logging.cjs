const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[];
const ctx={window:{},URL,Uint8Array,AbortController,DOMException,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto,
 performance:{now:()=>123},location:{origin:'https://example.com',replace(){}},
 fetch:async(url,opts)=>{calls.push({url,opts}); if(url==='/api/auth/client-failure')return {ok:true};
 if(url.includes('invalid'))return {ok:true,status:200,json:async()=>{throw new SyntaxError('bad body contains secret');}};
 if(url.includes('offline'))throw new TypeError('secret must not be logged');
 if(opts.signal?.aborted)throw Object.assign(new Error(),{name:'AbortError'});
 return {ok:false,status:504};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/core/auth-client.js','utf8'),ctx);
(async()=>{
 await ctx.window.FinFeedAuth.request('/api/state?user=private');
 let report=JSON.parse(calls[1].opts.body);
 assert.equal(report.path,'/api/state');assert.equal(report.status,504);
 assert.equal(report.request_id,calls[0].opts.headers['X-FinFeed-Request-ID']);
 await assert.rejects(ctx.window.FinFeedAuth.request('/api/offline?token=private'));
 report=JSON.parse(calls.at(-1).opts.body);assert.equal(report.category,'network_error');
 assert(!calls.at(-1).opts.body.includes('private'));assert(!calls.at(-1).opts.body.includes('secret'));
 const invalid=await ctx.window.FinFeedAuth.request('/api/invalid');await assert.rejects(invalid.json());
 assert.equal(JSON.parse(calls.at(-1).opts.body).category,'invalid_response');
 const before=calls.length;await assert.rejects(ctx.window.FinFeedAuth.request('/api/state',{signal:{aborted:true}}));
 assert.equal(calls.length,before+1);
 // Safari may report AbortError even when our deadline caused the abort.
 let deadline;
 ctx.setTimeout=callback=>{deadline=callback;return 1;};
 const originalFetch=ctx.fetch;
 ctx.fetch=(url,options)=>url==='/api/auth/client-failure'?originalFetch(url,options):new Promise((_,reject)=>{
   options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('Fetch is aborted'),{name:'AbortError'})));
 });
 const timedOut=ctx.window.FinFeedAuth.request('/api/auth/status');deadline();
 await assert.rejects(timedOut,error=>error.name==='TimeoutError'&&error.message==='API 请求超过 30 秒');
 assert.equal(JSON.parse(calls.at(-1).opts.body).category,'timeout');
 console.log('API failure reporting tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
