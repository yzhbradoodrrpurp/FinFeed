"use strict";
// Native WebAuthn: private keys and biometrics stay with the authenticator.
window.FinFeedAuth = (() => {
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
    let response;
    try {
      response = await fetch(url, {...options, credentials:"same-origin", headers:{...options.headers,"X-FinFeed-Client":"1","X-FinFeed-Request-ID":requestId}});
    } catch(error) {
      if(error.name !== 'AbortError')reportFailure(url, options, 'network_error', null, started, requestId);
      throw error;
    }
    const readJSON = response.json?.bind(response);
    if(readJSON)response.json = async () => {
      try { return await readJSON(); }
      catch(error) { reportFailure(url, options, 'invalid_response', response.status, started, requestId); throw error; }
    };
    if(!response.ok)reportFailure(url, options, 'http_error', response.status, started, requestId);
    if(response.status===401 && !url.startsWith("/api/auth/")) {
      location.replace("/login");throw new Error("登录已过期，请重新验证");
    }
    return response;
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
    const response=await request("/api/auth/status");
    if(!response.ok)throw new Error("无法检查登录状态，请稍后刷新");
    const status=await response.json();
    if(!status.authenticated){location.replace("/login");throw new Error("请先登录");}
    return status;
  }
  function message(error) {
    if(error.name==="NotAllowedError")return "验证已取消或超时，请重试。";
    if(error.name==="InvalidStateError")return "这把 Passkey 已绑定，请使用它登录或选择另一把。";
    return error.message||"验证失败，请重试。";
  }
  return {request,post,passkey,initialize,message};
})();
