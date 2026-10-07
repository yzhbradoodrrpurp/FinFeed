"use strict";
const fs=require("node:fs"),path=require("node:path");
const out=path.join(__dirname,"dist");
fs.rmSync(out,{recursive:true,force:true});fs.mkdirSync(out);
const assets=require("../dashboard/frontend/manifest.json");
for(const name of ["index.html","style.css","app.js","positions.js","macro.js","whales.js","home.js","cache.js","auth-client.js","login.js","dropdowns.js","motion.js","whale-analysis.js","ticker-search.js","symbol-directory.json","news.js"])
  fs.copyFileSync(path.join(__dirname,"../dashboard/frontend",assets[name]),path.join(out,name));
for(const name of ["bridge.html","callback.html","bridge.js"])
  fs.copyFileSync(path.join(__dirname,name),path.join(out,name));
console.log("Built FinFeed static frontend; credentials and account data remain on the backend.");
