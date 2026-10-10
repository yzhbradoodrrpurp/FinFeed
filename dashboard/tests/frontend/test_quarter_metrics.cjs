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
 assert.deepEqual(Array.from(group.columns,c=>c[2]),group.name==='资本开支'?['Q0 · 单季','Q0 · 季度同比','Q0 · 季度环比','Q−1 · 季度环比']:['Q0','Q0 · 去年同期','Q−1','Q−2']);
}
assert.deepEqual(Array.from(added.find(g=>g.name==='资本开支').columns,c=>c[3]),['money','growth','growth','growth']);
assert.equal(context.format({value:.5},'growth'),'+50.0%');
assert.equal(context.format({value:.4},'percent'),'40.00%');
assert.equal(context.format({value:-.1},'percent'),'-10.00%');
assert.equal(context.format({value:null},'percent'),'—');
assert.equal(context.format({value:1e9},'money'),'1.00B');
console.log('PASS: Watchlist quarter groups, column order, margin percentages and existing money formatting');
