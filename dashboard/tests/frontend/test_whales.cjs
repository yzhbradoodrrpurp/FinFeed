const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const pending=new Map(),nodes=new Map();
function node(id,dataset={}){const n={hidden:false,dataset,textContent:'',innerHTML:'',setAttribute(k,v){this[k]=v},focus(){},insertAdjacentHTML(_p,s){this.innerHTML+=s},addEventListener(_e,f){this.click=f}};nodes.set(id,n);return n;}
['whales-refresh','whales-surface','whales-list','whale-detail','whale-detail-title','whale-detail-summary','whale-detail-content','whale-back','whale-stock-search','whale-stock-results','whale-stock-content'].forEach(x=>node(x));
const funds=['berkshire','pershing','appaloosa','ark','coatue','altimeter','tiger','polar','alkeon','westfield','lightstreet','hmi','atika','dorsey','altarock','broadrun','mubadala','bridgewater'];const buttons=funds.map(x=>node('button-'+x,{whale:x}));funds.forEach(x=>node('whale-summary-'+x));
const tabs=['latest','previous','changes'].map(x=>node('tab-'+x,{whaleTab:x}));
const ctx={window:{addEventListener(){}},location:{href:'https://example.com/?surface=whales'},history:{replaceState(_s,_t,u){ctx.location.href=String(u)}},URL,document:{addEventListener(){},hidden:false,getElementById:id=>nodes.get(id),querySelectorAll:s=>s==='[data-whale]'?buttons:s==='[data-whale-tab]'?tabs:[],querySelector:s=>buttons.find(b=>s.includes('"'+b.dataset.whale+'"'))},Intl,Date,Number,Map,Promise,setInterval(){},FinFeedCache:{read:()=>null,write(){},market:(url,consume)=>new Promise(resolve=>pending.set(url,{consume,resolve}))}};
const row={name:'<APPLE>',class:'COM',cusip:'037833100',shares:10,value:100,weight:100,amount_type:'SH'};
const data={schema_version:3,totals_verified:true,report_date:'2026-06-30',filed_at:'2026-08-14',retrieved_at:'2026-10-06T04:00:00Z',total_value:100,holdings:[row],sources:[],previous_status:'available',previous:{report_date:'2026-03-31',filed_at:'2026-05-15',total_value:80,holdings:[{...row,shares:8,value:80}],sources:[]},changes:[{...row,status:'increase',previous_shares:8,current_shares:10,shares_change:2,shares_change_percent:25,previous_value:80,current_value:100,weight_change:0}]};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/../../frontend/js/views/whales.js','utf8'),ctx);
(async()=>{
 ctx.window.FinFeedWhales.open();assert.equal(pending.size,2);
 const first=pending.get('/api/whales/berkshire?version=10&stream=1');first.consume(data);first.resolve();
 buttons[0].click();assert.equal(nodes.get('whales-list').hidden,true);assert.match(ctx.location.href,/fund=berkshire/);
 assert.match(nodes.get('whale-detail-content').innerHTML,/&lt;APPLE&gt;/);assert.doesNotMatch(nodes.get('whale-detail-content').innerHTML,/成本|implied_price/);
 tabs[1].click();assert.match(nodes.get('whale-detail-content').innerHTML,/2026-03-31/);
 tabs[2].click();assert.match(nodes.get('whale-detail-content').innerHTML,/增持/);assert.match(nodes.get('whale-detail-content').innerHTML,/25.00%/);
 nodes.get('whale-back').click();assert.equal(nodes.get('whale-detail').hidden,true);assert.doesNotMatch(ctx.location.href,/fund=/);
 for(let round=0;round<funds.length;round++){for(const p of pending.values()){p.consume(data);p.resolve();}await new Promise(setImmediate);}
 buttons.find(b=>b.dataset.whale==='mubadala').click();assert.match(ctx.location.href,/fund=mubadala/);assert.match(nodes.get('whale-detail-title').textContent,/穆巴达拉投资/);nodes.get('whale-back').click();
 buttons.at(-1).click();assert.match(ctx.location.href,/fund=bridgewater/);assert.match(nodes.get('whale-detail-title').textContent,/桥水基金/);nodes.get('whale-back').click();
 nodes.get('whales-refresh').click();const failed=pending.get('/api/whales/berkshire?version=10&stream=1&refresh=1');failed.consume({holdings:[],errors:['failure']});failed.resolve();buttons[0].click();assert.match(nodes.get('whale-detail-content').innerHTML,/037833100/);assert.match(nodes.get('whale-detail-summary').textContent,/旧数据/);
 console.log('PASS: parallel requests, immediate display, institution navigation, quarter tabs, changes, no cost calculation and failure cache');
})().catch(error=>{console.error(error);process.exitCode=1;});
