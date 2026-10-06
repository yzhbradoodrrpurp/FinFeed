const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/public/macro.js','utf8');
const functions=source.slice(source.indexOf('  function bindChart('),source.indexOf('  function metricValue('));
const rows=[{date:'2026-10-01',value:101},{date:'2026-10-02',value:102},{date:'2026-10-05',value:104}];
function node(){return {attrs:{},setAttribute(k,v){this.attrs[k]=v}};}
const vertical=node(),horizontal=node(),dot=node(),crosshair=node();
crosshair.querySelector=s=>s==='circle'?dot:s.includes('vertical')?vertical:horizontal;
const tooltip={hidden:true,style:{},offsetWidth:140,offsetHeight:24};
const handlers={};
const identity={inverse(){return this}};
const svg={querySelector:s=>s==='polyline'?{points:{getItem:i=>({x:8+i*100,y:60-i*10})}}:crosshair,addEventListener(k,f){handlers[k]=f},getScreenCTM:()=>identity,createSVGPoint:()=>({matrixTransform(){return {x:this.x,y:this.y}}})};
const figure={querySelector:s=>s==='svg'?svg:tooltip,getBoundingClientRect:()=>({left:0,top:0,width:400})};
const context={chartRows:m=>m.history,number:v=>String(v),Date,Number,Math};
vm.createContext(context);vm.runInContext(functions+'\nthis.bindChart=bindChart;',context);
context.bindChart({querySelector:()=>figure},{history:rows,unit:'点'});
// Saturday (Oct 3) selects the actual Friday observation; y does not change the selected date.
handlers.pointermove({clientX:200,clientY:50});
assert.equal(tooltip.textContent,'2026-10-02 · 102点');
assert.equal(vertical.attrs.x1,108);assert.equal(horizontal.attrs.y1,50);
handlers.pointermove({clientX:200,clientY:80});assert.equal(tooltip.textContent,'2026-10-02 · 102点');
handlers.pointermove({clientX:500,clientY:50});assert.equal(tooltip.textContent,'2026-10-05 · 104点');
handlers.pointerleave();assert.equal(tooltip.hidden,true);assert.equal(crosshair.attrs.visibility,'hidden');
handlers.keydown({key:'Home',preventDefault(){}});assert.equal(tooltip.textContent,'2026-10-01 · 101点');
handlers.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(tooltip.textContent,'2026-10-02 · 102点');
context.bindChart({querySelector:()=>figure},{history:rows,unit:'%'});
handlers.keydown({key:'End',preventDefault(){}});assert.equal(tooltip.textContent,'2026-10-05 · 104%');
console.log('PASS: pointer snaps to real dates, both crosshair axes track the observation, keyboard navigation and units work');
