const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../../frontend/js/core/auth-client.js','utf8');
function fixture(expiry,authenticated=true){
 const values=new Map(expiry===undefined?[]:[['finfeed-session-expires',String(expiry)]]), redirects=[],requests=[];
 let pending=true;
 const context={window:{},localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},
 document:{documentElement:{classList:{contains:()=>pending,toggle:(key,value)=>pending=value}},getElementById:()=>null},
 location:{origin:'https://example.com',replace:url=>redirects.push(url)},performance,crypto:require('node:crypto').webcrypto,AbortController,DOMException,URL,Uint8Array,setTimeout,clearTimeout,
 fetch:async(url)=>{requests.push(url);return {ok:true,status:200,headers:{get:key=>key==='X-FinFeed-Session-Max-Age'&&url.includes('verify')?'43200':null},json:async()=>({authenticated,sessionExpiresIn:120,user:{id:'test'}})};}};
 vm.createContext(context);vm.runInContext(source,context);
 return {auth:context.window.FinFeedAuth,values,redirects,requests,pending:()=>pending};
}
(async()=>{
 const expired=fixture(Date.now()-1000);
 assert.deepEqual(expired.redirects,['/login']);
 await assert.rejects(expired.auth.initialize(),error=>error.code==='AUTH_REDIRECT');
 assert.deepEqual(expired.requests,[]);
 const legacy=fixture();await legacy.auth.initialize();assert.deepEqual(legacy.requests,['/api/auth/status']);
 assert(Number(legacy.values.get('finfeed-session-expires'))>Date.now());
 const revoked=fixture(Date.now()+100000,false);await assert.rejects(revoked.auth.initialize(),error=>error.code==='AUTH_REDIRECT');
 assert.deepEqual(revoked.redirects,['/login']);assert.equal(revoked.values.size,0);
 const login=fixture();await login.auth.post('/api/auth/login/verify');
 assert(Number(login.values.get('finfeed-session-expires'))>Date.now()+43100000);
 await login.auth.post('/api/auth/logout');assert.equal(login.values.size,0);
 console.log('PASS: known expired sessions redirect before data requests; hints never bypass server validation; login/logout update expiry');
})().catch(error=>{console.error(error);process.exitCode=1;});
