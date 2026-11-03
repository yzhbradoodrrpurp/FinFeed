'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../frontend/js/views/candles.js'),'utf8');
const readers=source.slice(source.indexOf('  async function readDrawings('),source.indexOf('  async function saveDrawing('));
const nodes={retry:{},discard:{},tools:{querySelector:()=>nodes.pen},pen:{}};
const state={symbol:'MSFT',revision:0,loaded:false,lines:[]},timers=[];
let attempts=0;
const context={drawState:state,dragEdit:null,dialog:{open:true},deleteButton:null,encodeURIComponent,
 node:key=>nodes[key],toolStatus:()=>{},redraw:()=>{},writeDrawingCache:()=>{},clearTimeout:()=>{},setTimeout:fn=>{timers.push(fn);return timers.length;},
 FinFeedAuth:{request:async(url,options)=>{assert.equal(options.timeoutMs,10000);if(++attempts===1)throw Error('network');return {ok:true,status:200,json:async()=>({revision:2,lines:[{id:'saved-line'}],cache_version:'v'})};}}};
vm.runInNewContext(readers+'\nglobalThis.read=readDrawings;',context);
(async()=>{
 await context.read();assert.equal(nodes.pen.disabled,true);assert.equal(timers.length,1);
 await timers.shift()();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(state.loaded,true);assert.equal(nodes.pen.disabled,false);assert.equal(state.lines[0].id,'saved-line');assert.equal(state.readFailures,0);
 context.dialog.open=false;assert.equal(timers.length,0);
 console.log('PASS: failed private drawing GET retries and restores saved lines and pen access');
})().catch(error=>{console.error(error);process.exitCode=1;});
