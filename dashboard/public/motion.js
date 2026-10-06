"use strict";
// Only user navigation animates; background data updates never restart motion.
window.FinFeedMotion=(()=>{
  const running=new WeakMap();
  function enter(element,{kind='surface',direction=1}={}){
    if(!element||element.hidden||!element.animate)return;
    running.get(element)?.cancel();
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    // Direction follows navigation order; filters/accounts stay spatially neutral.
    const presets={
      surface:{transform:`translateX(${direction*24}px)`,duration:340},
      detail:{transform:`translateX(${direction*32}px)`,duration:360},
      tab:{transform:`translateX(${direction*18}px)`,duration:260},
      account:{transform:'translateY(6px)',duration:240},
      filter:{transform:'none',duration:220}
    };
    const preset=presets[kind]||presets.surface;
    const animation=element.animate([
      {opacity:0,transform:preset.transform},
      {opacity:1,transform:'translateY(0)'}
    ],{duration:preset.duration,easing:'cubic-bezier(.22,1,.36,1)'});
    running.set(element,animation);
    animation.onfinish=()=>{if(running.get(element)===animation)running.delete(element);};
  }
  return {enter};
})();
