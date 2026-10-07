"use strict";
let setupRequired=false,signup=new URLSearchParams(location.search).get("register")==="1",controller=null;
const button=document.getElementById("passkey-submit"),errorBox=document.getElementById("login-error");
const loginParams=new URLSearchParams(location.search),frontendLogin=loginParams.get("frontend")==="1";
if(frontendLogin){const signupParams=new URLSearchParams(loginParams);signupParams.set("register","1");document.getElementById("signup-link").href="/login?"+signupParams;}
function error(message){errorBox.textContent=message;errorBox.hidden=false;}
function showMode(){
  document.getElementById("signup-fields").hidden=!signup;
  document.getElementById("setup-fields").hidden=signup||!setupRequired;
  button.textContent=signup?"创建账户并保存 Passkey":setupRequired?"绑定我的 Passkey":"使用 Passkey 登录";
  const link=document.getElementById("signup-link"),params=new URLSearchParams(loginParams);
  if(signup)params.delete("register");else params.set("register","1");
  link.href="/login?"+params;
  link.textContent=signup?"已有账户？返回登录":"首次使用？通过邀请码创建账户";
  document.getElementById("login-description").textContent=signup?"填写邀请码和账户名称，保存 Passkey 后即可创建账户。":"使用已保存的 Passkey 登录。";
}
async function authenticate(){
  controller?.abort();const active=new AbortController();controller=active;
  button.disabled=true;errorBox.hidden=true;
  try{
    const code=document.getElementById("setup-code").value.trim();
    if(setupRequired&&!signup&&!code)throw new Error("请输入首次绑定码");
    const extra=signup?{newAccount:true,name:document.getElementById("account-name").value.trim(),inviteCode:document.getElementById("invite-code").value.trim()}:{};
    if(signup&&!extra.inviteCode)throw new Error("请输入邀请码");
    if(signup&&!extra.name)throw new Error("请输入账户名称");
    await FinFeedAuth.passkey(signup||setupRequired,code,"我的 Passkey",extra,{signal:active.signal});
    if(active.signal.aborted)return;
    document.getElementById("setup-code").value="";document.getElementById("invite-code").value="";
    if(frontendLogin){
      const result=await FinFeedAuth.post("/api/auth/frontend-ticket",{challenge:loginParams.get("challenge"),state:loginParams.get("state")});
      location.replace(result.redirect);
    }else location.replace("/");
  }catch(e){if(!active.signal.aborted)error(FinFeedAuth.message(e));}
  finally{if(controller===active){controller=null;button.disabled=false;}}
}
(async()=>{
  try{
    const response=await FinFeedAuth.request("/api/auth/status");
    if(!response.ok)throw new Error("无法连接验证服务，请稍后刷新");
    const status=await response.json();
    if(status.authenticated&&!frontendLogin){location.replace("/");return;}
    setupRequired=status.setupRequired;showMode();
    if(!window.PublicKeyCredential)throw new Error("当前浏览器不支持 Passkey，请使用新版 Safari、Chrome 或 Edge。");
    button.disabled=false;
    if(!signup&&!setupRequired&&!new URLSearchParams(location.search).has("manual"))await authenticate();
  }catch(e){error(FinFeedAuth.message(e));button.textContent="暂时无法登录";}
})();
document.getElementById("passkey-form").addEventListener("submit",event=>{event.preventDefault();authenticate();});
