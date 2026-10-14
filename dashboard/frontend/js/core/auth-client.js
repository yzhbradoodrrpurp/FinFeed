"use strict";
// Native WebAuthn: private keys and biometrics stay with the authenticator.
window.FinFeedAuth = (() => {
  let redirectError=null;
  const expiryKey="finfeed-session-expires";
  function rememberExpiry(seconds) {
    try { localStorage.setItem(expiryKey,String(Date.now()+Number(seconds)*1000)); } catch {}
  }
  function redirectToLogin() {
    try { localStorage.removeItem(expiryKey); } catch {}
    setGate(true);
    location.replace("/login");
    const error=new Error("登录已过期，请重新验证");
    error.code="AUTH_REDIRECT";
    redirectError=error;
    return error;
  }
  function knownExpired() {
    try { const expiry=Number(localStorage.getItem(expiryKey));return expiry>0&&Date.now()>=expiry; } catch { return false; }
  }
  function setGate(pending, message="正在检查登录状态…") {
    if(typeof document==="undefined")return;
    document.documentElement?.classList.toggle("auth-pending",pending);
    const status=document.getElementById("auth-gate");
    if(status){status.hidden=!pending;status.textContent=message;}
  }
  function checkResumedSession() {
    if(!redirectError&&knownExpired())redirectToLogin();
  }
  if(typeof document!=="undefined"&&document.documentElement?.classList.contains("auth-pending")) {
    window.addEventListener?.("pageshow",checkResumedSession);
    document.addEventListener?.("visibilitychange",()=>{if(!document.hidden)checkResumedSession();});
  }
  // This synchronous head script can redirect before the dashboard is parsed.
  if(typeof document!=="undefined"&&document.documentElement?.classList.contains("auth-pending")&&knownExpired())redirectToLogin();
  const decode = value => Uint8Array.from(atob(value.replace(/-/g,"+").replace(/_/g,"/") + "=".repeat((4-value.length%4)%4)), c=>c.charCodeAt(0));
  const encode = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
  function reportFailure(url, options, category, status, started, requestId) {
    if(url === '/api/auth/client-failure')return;
    // Never transmit query strings, response bodies, cookies or error messages.
    const path = new URL(url, location.origin).pathname;
    void fetch('/api/auth/client-failure', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-FinFeed-Client':'1'},
      body:JSON.stringify({path, method:options.method||'GET', category, status,
        elapsed_ms:Math.round(performance.now()-started), request_id:requestId})}).catch(()=>{});
  }
  async function request(url, options={}) {
    const started=performance.now();
    const requestId=Array.from(crypto.getRandomValues(new Uint8Array(8)), b=>b.toString(16).padStart(2,'0')).join('');
    const controller=new AbortController();
    const abort=()=>controller.abort(options.signal?.reason);
    if(options.signal?.aborted)abort();else options.signal?.addEventListener?.('abort',abort,{once:true});
    const timer=setTimeout(()=>controller.abort(new DOMException(`API 请求超过 ${options.timeoutMs?options.timeoutMs/1000:30} 秒`,'TimeoutError')),options.timeoutMs||30000);
    const finish=()=>{clearTimeout(timer);options.signal?.removeEventListener?.('abort',abort);};
    let response;
    try {
      response = await fetch(url, {...options, signal:controller.signal, credentials:"same-origin", headers:{...options.headers,"X-FinFeed-Client":"1","X-FinFeed-Request-ID":requestId}});
    } catch(error) {
      finish();
      if(controller.signal.reason?.name==='TimeoutError')reportFailure(url, options, 'timeout', null, started, requestId);
      else if(error.name !== 'AbortError')reportFailure(url, options, 'network_error', null, started, requestId);
      throw controller.signal.reason?.name==='TimeoutError' ? controller.signal.reason : error;
    }
    const maxAge=response.headers?.get("X-FinFeed-Session-Max-Age");
    if(response.ok&&maxAge!==null&&maxAge!==undefined&&Number(maxAge)>0)rememberExpiry(maxAge);
    if(response.ok&&url==="/api/auth/logout") {
      try { localStorage.removeItem(expiryKey); } catch {}
    }
    const readJSON = response.json?.bind(response);
    if(readJSON)response.json = async () => {
      try { return await readJSON(); }
      catch(error) { reportFailure(url, options, controller.signal.reason?.name==='TimeoutError'?'timeout':'invalid_response', response.status, started, requestId); throw controller.signal.reason?.name==='TimeoutError' ? controller.signal.reason : error; }
      finally { finish(); }
    };
    // Stream readers have their own full-body deadline in FinFeedCache.market.
    if(!readJSON||response.headers?.get('content-type')?.includes('ndjson'))finish();
    if(!response.ok)reportFailure(url, options, 'http_error', response.status, started, requestId);
    if(response.status===401 && !url.startsWith("/api/auth/")) {
      finish();throw redirectToLogin();
    }
    return response;
  }
  async function read(url, {signal,...options}={}) {
    // Retry complete JSON reads only: mutations and market streams are not replayed.
    const retryable=new Set([408,429,502,503,504]);
    for(let attempt=0;attempt<3;attempt++) {
      try {
        const response=await request(url,{...options,method:"GET",signal,timeoutMs:10000});
        if(!response.ok) {
          if(response.json)await response.json().catch(()=>{});
          const error=new Error(`读取失败 (${response.status})`);error.retryable=retryable.has(response.status);throw error;
        }
        return await response.json();
      } catch(error) {
        if(signal?.aborted||error.code==='AUTH_REDIRECT'||error.name==='AbortError'||
           !(error.retryable||error.name==='TypeError'||error.name==='SyntaxError'||error.name==='TimeoutError')||attempt===2)throw error;
        await new Promise((resolve,reject)=>{
          const abort=()=>{clearTimeout(timer);reject(signal.reason||new DOMException('已取消','AbortError'));};
          const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},500*(attempt+1));
          if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
        });
      }
    }
  }
  async function post(url, body={}) {
    const response = await request(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data = await response.json();
    if(!response.ok)throw new Error(data.error||"验证失败，请重试");
    return data;
  }
  function credentialJSON(credential) {
    const response = credential.response;
    const result = {id:credential.id,rawId:encode(credential.rawId),type:credential.type,
      authenticatorAttachment:credential.authenticatorAttachment,
      clientExtensionResults:credential.getClientExtensionResults(),response:{clientDataJSON:encode(response.clientDataJSON)}};
    for(const key of ["attestationObject","authenticatorData","signature","userHandle"])
      if(response[key])result.response[key]=encode(response[key]);
    if(response.getTransports)result.response.transports=response.getTransports();
    return result;
  }
  async function passkey(register=false, setupCode="", label="我的 Passkey", extra={}, credentialOptions={}) {
    if(!window.isSecureContext || !navigator.credentials || !window.PublicKeyCredential)
      throw new Error("当前浏览器不支持 Passkey，请使用新版 Safari、Chrome 或 Edge，并通过 HTTPS 访问");
    const action=register?"register":"login";
    const options=await post(`/api/auth/${action}/options`,register?{setupCode,label,...extra}:{});
    options.challenge=decode(options.challenge);
    if(options.user)options.user.id=decode(options.user.id);
    for(const key of ["allowCredentials","excludeCredentials"])
      if(options[key])options[key]=options[key].map(item=>({...item,id:decode(item.id)}));
    const credential=await navigator.credentials[register?"create":"get"]({publicKey:options,...credentialOptions});
    if(!credential)throw new Error("验证已取消");
    await post(`/api/auth/${action}/verify`,credentialJSON(credential));
  }
  async function initialize() {
    if(redirectError)throw redirectError;
    if(knownExpired())throw redirectToLogin();
    const status=await read("/api/auth/status");
    if(!status.authenticated)throw redirectToLogin();
    if(Number(status.sessionExpiresIn)>0)rememberExpiry(status.sessionExpiresIn);
    return status;
  }
  function message(error) {
    if(error.name==="NotAllowedError")return "验证已取消或超时，请重试。";
    if(error.name==="InvalidStateError")return "这把 Passkey 已绑定，请使用它登录或选择另一把。";
    return error.message||"验证失败，请重试。";
  }
  return {request,read,post,passkey,initialize,message,setGate};
})();
