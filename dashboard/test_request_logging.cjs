const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[];
const ctx={window:{},URL,Uint8Array,crypto:require('node:crypto').webcrypto,
 performance:{now:()=>123},location:{origin:'https://example.com',replace(){}},
 fetch:async(url,opts)=>{calls.push({url,opts}); if(url==='/api/auth/client-failure')return {ok:true};
 if(url.includes('offline'))throw new TypeError('secret must not be logged');
 if(opts.signal?.aborted)throw Object.assign(new Error(),{name:'AbortError'});
 return {ok:false,status:504};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/public/auth-client.js','utf8'),ctx);
(async()=>{
 await ctx.window.FinFeedAuth.request('/api/state?user=private');
 let report=JSON.parse(calls[1].opts.body);
 assert.equal(report.path,'/api/state');assert.equal(report.status,504);
 assert.equal(report.request_id,calls[0].opts.headers['X-FinFeed-Request-ID']);
 await assert.rejects(ctx.window.FinFeedAuth.request('/api/offline?token=private'));
 report=JSON.parse(calls.at(-1).opts.body);assert.equal(report.category,'network_error');
 assert(!calls.at(-1).opts.body.includes('private'));assert(!calls.at(-1).opts.body.includes('secret'));
 const before=calls.length;await assert.rejects(ctx.window.FinFeedAuth.request('/api/state',{signal:{aborted:true}}));
 assert.equal(calls.length,before+1);
 console.log('API failure reporting tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
