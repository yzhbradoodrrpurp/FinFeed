const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const bodies=new Map(),callbacks=new Map(),pending=new Map();
const button={disabled:false,addEventListener:(_event,handler)=>callbacks.set('refresh',handler)};
const data=kind=>({fund:kind,report_date:'2026-06-30',filed_at:'2026-08-14',retrieved_at:'2026-10-06T04:00:00Z',total_value:100,holdings:[{name:'<APPLE>',class:'COM',cusip:'037833100',shares:10,value:100,weight:100,amount_type:'SH'}],sources:[{url:'https://www.sec.gov/Archives/test.txt',form:'13F-HR'}]});
const ctx={window:{},document:{hidden:false,getElementById:id=>id==='whales-refresh'?button:id==='whales-surface'?{hidden:false}:{querySelector:()=>bodies.get(id),appendChild:body=>bodies.set(id,body)},createElement:()=>({setAttribute(){},innerHTML:''})},Intl,Date,Number,Map,Promise,setInterval(){},FinFeedCache:{read:()=>null,write(){},market:(url,consume)=>new Promise(resolve=>pending.set(url,{consume,resolve}))}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/public/whales.js','utf8'),ctx);
(async()=>{
 ctx.window.FinFeedWhales.open();assert.equal(pending.size,2);
 const first=pending.get('/api/whales/berkshire?stream=1');first.consume(data('berkshire'));first.resolve();
 assert.match(bodies.get('whale-berkshire').innerHTML,/&lt;APPLE&gt;/);
 assert.doesNotMatch(bodies.get('whale-pershing').innerHTML,/报告期末/);
 const second=pending.get('/api/whales/pershing?stream=1');second.consume(data('pershing'));second.resolve();await new Promise(setImmediate);
 callbacks.get('refresh')();const failed=pending.get('/api/whales/berkshire?stream=1');failed.consume({holdings:[],errors:['failure']});failed.resolve();
 assert.match(bodies.get('whale-berkshire').innerHTML,/保留旧数据/);assert.match(bodies.get('whale-berkshire').innerHTML,/037833100/);
 console.log('PASS: fund requests start concurrently; each renders immediately; failed refresh preserves holdings; issuer text escapes HTML');
})().catch(error=>{console.error(error);process.exitCode=1;});
