"use strict";
(async()=>{
  const encode=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
  const status=document.getElementById("bridge-status");
  try{
    if(location.pathname==="/auth/callback"){
      const params=new URLSearchParams(location.hash.slice(1));
      history.replaceState(null,"",location.pathname);
      const pending=JSON.parse(sessionStorage.getItem("finfeed-login")||"null");
      sessionStorage.removeItem("finfeed-login");
      if(!pending||params.get("state")!==pending.state||Date.now()-pending.created>300000)
        throw new Error("登录链接无效或已过期，请重新登录。");
      await FinFeedAuth.post("/api/auth/frontend-exchange",{ticket:params.get("ticket"),verifier:pending.verifier});
      location.replace("/");
    }else if(new URLSearchParams(location.search).has("legacy")){
      const verifier=encode(crypto.getRandomValues(new Uint8Array(32))),state=encode(crypto.getRandomValues(new Uint8Array(32)));
      const challenge=encode(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(verifier)));
      sessionStorage.setItem("finfeed-login",JSON.stringify({verifier,state,created:Date.now()}));
      const params=new URLSearchParams({frontend:"1",challenge,state});
      if(new URLSearchParams(location.search).get("register")==="1")params.set("register","1");
      location.replace("https://finfeed-private.onrender.com/login?"+params);
    }
  }catch(error){(status||document.getElementById("login-error")).textContent=error.message||"无法完成登录，请重试。";}
})();
