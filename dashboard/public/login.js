"use strict";
let setupRequired=false;
const button=document.getElementById("passkey-submit"),errorBox=document.getElementById("login-error");
function error(message){errorBox.textContent=message;errorBox.hidden=false;}
(async()=>{
  try{
    const response=await FinFeedAuth.request("/api/auth/status");
    if(!response.ok)throw new Error("无法连接验证服务，请稍后刷新");
    const status=await response.json();
    if(status.authenticated){location.replace("/");return;}
    setupRequired=status.setupRequired;
    document.getElementById("setup-fields").hidden=!setupRequired;
    document.getElementById("login-description").textContent=setupRequired?"第一次使用：验证绑定码，并为你的私人账户创建 Passkey。":"使用 Passkey 验证身份，查看你的自选股和持仓。";
    if(setupRequired&&!status.bootstrapAvailable)throw new Error("尚未配置首次绑定码，请在部署平台完成配置后刷新。");
    if(!window.PublicKeyCredential)throw new Error("当前浏览器不支持 Passkey，请使用新版 Safari、Chrome 或 Edge。");
    button.textContent=setupRequired?"绑定我的 Passkey":"使用 Passkey 登录";
    button.disabled=false;
  }catch(e){error(FinFeedAuth.message(e));button.textContent="暂时无法登录";}
})();
document.getElementById("passkey-form").addEventListener("submit",async event=>{
  event.preventDefault();button.disabled=true;errorBox.hidden=true;
  try{
    const code=document.getElementById("setup-code").value.trim();
    if(setupRequired&&!code)throw new Error("请输入首次绑定码");
    await FinFeedAuth.passkey(setupRequired,code);
    document.getElementById("setup-code").value="";
    location.replace("/");
  }catch(e){error(FinFeedAuth.message(e));button.disabled=false;}
});
