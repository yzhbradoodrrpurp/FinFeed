const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const window={};vm.runInNewContext(fs.readFileSync(__dirname+'/public/whale-analysis.js','utf8'),{window});
const api=window.FinFeedWhaleAnalysis;
const stock=(shares,extra={})=>({cusip:'ABC123456',name:'Example',class:'COM',amount_type:'SH',put_call:'',shares,value:shares*10,weight:10,...extra});
const snapshot=(old,now,extra={})=>({totals_verified:true,report_date:'2026-06-30',holdings:now,previous:{totals_verified:true,report_date:'2026-03-31',holdings:old},...extra});
const states=new Map([
 ['increase',snapshot([stock(10)],[stock(15)])],['decrease',snapshot([stock(10)],[stock(5)])],
 ['unchanged',snapshot([stock(10)],[stock(10,{value:999})])],['new',snapshot([],[stock(8)])],
 ['exit',snapshot([stock(10)],[])],['neither',snapshot([],[stock(100,{put_call:'CALL'})])],
 ['missing',snapshot([stock(10)],[stock(10)],{previous:null})],
 ['nonadjacent',snapshot([stock(10)],[stock(10)],{previous:{totals_verified:true,report_date:'2025-12-31',holdings:[stock(10)]}})]]);
const funds=Object.fromEntries([...states.keys()].map(k=>[k,k]));
const result=api.analyze(states,funds,'ABC123456');
for(const key of ['increase','decrease','unchanged','new','exit'])assert.equal(result.groups[key].length,1,key);
assert.equal(result.groups.increase[0].percent,50);assert.equal(result.groups.exit[0].current.shares,0);
assert.equal(result.unavailable.length,2);assert.equal(result.absent.length,1);
assert.equal(api.securities(states).length,1);
const renamed=stock(5,{name:'New spelling',class:'COMMON STOCK'});
const duplicates=new Map([['a',snapshot([stock(10)],[stock(10),renamed])]]);
assert.equal(api.analyze(duplicates,{a:'A'},'ABC123456').groups.increase[0].current.shares,15);
assert.equal(api.securities(new Map([['a',snapshot([stock(10)],[])]]))[0].cusip,'ABC123456');
console.log('PASS: all five quantity statuses, exited securities, option exclusion, duplicate aggregation, missing/nonadjacent quarters');
const rankingStates=new Map([
 ['a',snapshot([],[stock(10),stock(20),stock(5,{cusip:'SECOND',name:'Second'}),stock(0,{cusip:'ZERO'}),stock(5,{cusip:'OPTION',put_call:'PUT'})])],
 ['b',snapshot([],[stock(5)])],
 ['older',snapshot([],[stock(5,{cusip:'OLD'})],{report_date:'2026-03-31'})],
 ['invalid',snapshot([],[stock(5,{cusip:'BAD'})],{totals_verified:false})]
]);
const ranked=api.topHeld(rankingStates);
assert.equal(ranked.report_date,'2026-06-30');assert.equal(ranked.covered,2);
assert.equal(ranked.rows.length,2);assert.equal(ranked.rows[0].count,2);
assert.equal(ranked.rows[0].cusip,'ABC123456');assert.equal(api.topHeld(rankingStates,1).rows.length,1);
assert.equal(api.topHeld(new Map([['a',rankingStates.get('a')]])).rows[0].count,1);
assert.equal(api.topHeld(new Map()).rows.length,0);
console.log('PASS: same-quarter ranking, unique institution counts, zero/option exclusion, limits and filtered scope');
