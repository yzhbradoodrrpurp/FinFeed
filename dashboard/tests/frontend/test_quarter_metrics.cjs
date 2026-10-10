const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('dashboard/frontend/js/core/app.js','utf8');
const context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('const groups = ['),source.indexOf('const allColumns='))+'\nglobalThis.groupsResult=groups;'+source.slice(source.indexOf('function format('),source.indexOf('function shortMissing(')),context);
const added=context.groupsResult.filter(g=>['毛利率','营业利润率','资本开支'].includes(g.name));
assert.equal(added.length,3);
for(const group of added){
 assert.equal(group.view,'financial');assert.equal(group.columns.length,4);
 assert.deepEqual(Array.from(group.columns,c=>c[2]),['Q0 · 单季','Q0 · 季度同比','Q0 · 季度环比','Q−1 · 季度环比']);
}
assert.deepEqual(Array.from(added.find(g=>g.name==='资本开支').columns,c=>c[3]),['money','growth','growth','growth']);
assert.equal(context.format({value:.5},'growth'),'+50.0%');
assert.equal(context.format({value:.4},'percent'),'40.00%');
assert.equal(context.format({value:-.1},'percent'),'-10.00%');
assert.equal(context.format({value:null},'percent'),'—');
assert.equal(context.format({value:1e9},'money'),'1.00B');
console.log('PASS: Watchlist quarter groups, column order, margin percentages and existing money formatting');

for(const group of added.filter(g=>g.name!=='资本开支'))assert.deepEqual(Array.from(group.columns,c=>c[3]),['percent','pp','pp','pp']);
assert.equal(context.format({value:.05},'pp'),'+5.0 pp');
assert.equal(context.format({value:-.05},'pp'),'-5.0 pp');
vm.runInContext(source.slice(source.indexOf('function normalizeFinancialComparisons('),source.indexOf('function seedQuoteSnapshots(')),context);
for(const [a,b,value,status] of [[0,-100,1,'归零'],[50,-100,1.5,'转正'],[-50,-100,.5,'负值收窄'],[-150,-100,-.5,'负值扩大'],[50,0,null,'由零转正'],[0,0,null,'持平']]){
 const record={metrics:{fcf_qoq_q0:{value:null,inputs:{current:a,previous_quarter:b}}}};
 context.normalizeFinancialComparisons(record);assert.equal(record.metrics.fcf_qoq_q0.value,value);assert.equal(record.metrics.fcf_qoq_q0.change_status,status);
}
const cached={metrics:{gross_margin_yoy_q0:{value:-1.5,inputs:{current:.05,previous_year_quarter:-.1}}}};
context.normalizeFinancialComparisons(cached);assert.ok(Math.abs(cached.metrics.gross_margin_yoy_q0.value-.15)<1e-12);
context.normalizeFinancialComparisons(cached);assert.ok(Math.abs(cached.metrics.gross_margin_yoy_q0.value-.15)<1e-12);
