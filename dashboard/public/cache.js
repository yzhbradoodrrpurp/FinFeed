"use strict";
// Public market snapshots only. Account records and credentials are never stored here.
window.FinFeedCache={
  read(key,maxAge=7*86400000){
    try{const value=JSON.parse(localStorage.getItem('finfeed-market:v1:'+key));
      return value&&value.data&&Number.isFinite(value.savedAt)&&Date.now()-value.savedAt>=0&&Date.now()-value.savedAt<=maxAge?value:null;
    }catch{return null;}
  },
  write(key,data){try{localStorage.setItem('finfeed-market:v1:'+key,JSON.stringify({data,savedAt:Date.now()}));}catch{}}
};
