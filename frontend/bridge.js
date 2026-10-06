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
    }
  }catch(error){(status||document.getElementById("login-error")).textContent=error.message||"无法完成登录，请重试。";}
})();
