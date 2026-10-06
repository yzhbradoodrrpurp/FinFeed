"use strict";
// Only user navigation animates; background data updates never restart motion.
window.FinFeedMotion=(()=>{
  const running=new WeakMap();
  function enter(element){
    if(!element||element.hidden||!element.animate)return;
    running.get(element)?.cancel();
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const animation=element.animate([
      {opacity:0.65,transform:'translateY(5px)'},
      {opacity:1,transform:'translateY(0)'}
    ],{duration:180,easing:'cubic-bezier(.2,.7,.2,1)'});
    running.set(element,animation);
    animation.onfinish=()=>{if(running.get(element)===animation)running.delete(element);};
  }
  return {enter};
})();
