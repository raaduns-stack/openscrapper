const KEY='harvestedResults';
const PAGE_KEY='capturedSerpPages';
const AUTO_KEY='serpAutoState';
const AUTH_KEY='scrappeeAuth';
const API='https://api.scrapee.uk';
const ALARM='scrappee-serp-resume';

async function readResults(){const v=await chrome.storage.local.get(KEY);return Array.isArray(v[KEY])?v[KEY]:[];}
async function badge(){const r=await readResults();await chrome.action.setBadgeText({text:r.length?String(Math.min(r.length,9999)):''});}
async function readAuth(){const v=await chrome.storage.local.get(AUTH_KEY);return v[AUTH_KEY]||null;}
async function writeAuth(auth){await chrome.storage.local.set({[AUTH_KEY]:auth});return auth;}
async function clearAuth(){await chrome.storage.local.remove(AUTH_KEY);}
async function readAuto(){const v=await chrome.storage.local.get(AUTO_KEY);return v[AUTO_KEY]||null;}
async function writeAuto(state){await chrome.storage.local.set({[AUTO_KEY]:state});return state;}
async function clearAuto(){await chrome.storage.local.remove(AUTO_KEY);}

async function api(path,options={}){
 const auth=await readAuth();
 const headers={'Content-Type':'application/json',...(options.headers||{})};
 if(auth?.token)headers.Authorization=`Bearer ${auth.token}`;
 const r=await fetch(API+path,{...options,headers});
 const text=await r.text();let data={};try{data=text?JSON.parse(text):{};}catch(_){data={detail:text};}
 if(!r.ok)throw new Error(data.detail||`API error ${r.status}`);
 return data;
}

async function validateAuth(){ const auth=await readAuth();
 if(!auth?.token)return {ok:false,reason:'missing'};
 try{
  const r=await fetch(`${API}/auth/me`,{headers:{Authorization:`Bearer ${auth.token}`}});
  if(r.ok){const data=await r.json();if(data?.email&&!auth.email)await writeAuth({...auth,email:data.email});return {ok:true,auth};}
  if(r.status===401){await clearAuth();return {ok:false,reason:'unauthorized'};}
  return {ok:true,auth};
 }catch(_){return {ok:true,auth};}
}

chrome.runtime.onInstalled.addListener(badge);
chrome.runtime.onStartup.addListener(async()=>{await badge();const s=await readAuto();if(s?.running)chrome.alarms.create(ALARM,{delayInMinutes:0.05});});

chrome.alarms.onAlarm.addListener(async alarm=>{
 if(alarm.name!==ALARM)return;
 try{await autoStep();}catch(e){await stopAuto(`Auto collection stopped: ${e.message||e}`);}
});

chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
 if(message?.type==='auth_get'){(async()=>sendResponse({ok:true,auth:await readAuth()}))().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auth_set'){(async()=>sendResponse({ok:true,auth:await writeAuth(message.auth)}))().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auth_clear'){(async()=>{await clearAuth();await stopAuto('Logged out.');sendResponse({ok:true});})().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auth_validate'){(async()=>sendResponse(await validateAuth()))().catch(e=>sendResponse({ok:false,error:String(e)}));return true;} if(message?.type==='auto_start'){(async()=>sendResponse(await startAuto(message.tabId)))().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auto_stop'){(async()=>{await stopAuto('Auto collection stopped.');sendResponse({ok:true});})().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auto_clear'){(async()=>{await stopAuto('Local SERP preview cleared.');await chrome.storage.local.remove([KEY,PAGE_KEY,AUTO_KEY]);await chrome.action.setBadgeText({text:''});sendResponse({ok:true});})().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auto_resume'){(async()=>{const s=await readAuto();if(!s?.running)return sendResponse({ok:false,error:'Auto collection is not running.'});s.waitingChallenge=false;await writeAuto(s);chrome.alarms.create(ALARM,{delayInMinutes:0.01});sendResponse({ok:true});})().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='auto_state'){(async()=>sendResponse({ok:true,state:await readAuto()}))().catch(e=>sendResponse({ok:false,error:String(e)}));return true;}
 if(message?.type==='serp_results'){
  (async()=>{const current=await readResults(),incoming=Array.isArray(message.results)?message.results:[],tagged=incoming.map((x,i)=>({...x,capture_id:`${Date.now()}-${sender.tab?.id||0}-${i}`,captured_at:new Date().toISOString()})),next=current.concat(tagged).slice(-10000);await chrome.storage.local.set({[KEY]:next});await badge();sendResponse({ok:true,count:next.length,added:tagged.length});})().catch(e=>sendResponse({ok:false,error:String(e)}));
  return true;
 }
});

async function startAuto(tabId){
 const tab=await chrome.tabs.get(tabId);
 if(!tab?.id||!/https?:\/\//.test(tab.url||'')||!/google\.|bing\./i.test(new URL(tab.url).hostname))throw new Error('Open a Google or Bing SERP first.');
 const scrap=await api('/scraps/current');
 if(!scrap)throw new Error('No active Current Scrap.');
 const session=await api('/serp/sessions',{method:'POST',body:JSON.stringify({scrap_id:scrap.id,ttl_seconds:86400})}); await api('/serp/sources',{method:'POST',body:JSON.stringify({token:session.token,url:tab.url})});
 const state={running:true,tabId,scrapId:scrap.id,scrapName:scrap.name,token:session.token,pages:0,results:0,waitingChallenge:false,lastPageKey:'',startedAt:new Date().toISOString(),message:'Starting…'};
 await writeAuto(state);await chrome.storage.local.remove([KEY,PAGE_KEY]);await badge();chrome.alarms.create(ALARM,{delayInMinutes:0.01});
 return {ok:true,state};
}

async function stopAuto(message='Auto collection stopped.'){
 const s=await readAuto();
 if(s){s.running=false;s.message=message;await writeAuto(s);}
 await chrome.alarms.clear(ALARM);
}

async function autoStep(){
 const state=await readAuto();
 if(!state?.running||state.waitingChallenge)return;
 let tab;
 try{tab=await chrome.tabs.get(state.tabId);}catch(_){return stopAuto('The SERP tab was closed.');}
 if(!tab?.url||!/google\.|bing\./i.test(new URL(tab.url).hostname))return stopAuto('SERP collection stopped because the active tab left Google/Bing.');
 if(tab.status&&tab.status!=='complete'){chrome.alarms.create(ALARM,{delayInMinutes:0.02});return;}
 const pageKey=normalizePage(tab.url);
 if(pageKey===state.lastPageKey){chrome.alarms.create(ALARM,{delayInMinutes:0.02});return;}
 const [{result}]=await chrome.scripting.executeScript({target:{tabId:state.tabId},func:captureSerpPage});
 if(!result?.ok){if(result?.challenge){state.waitingChallenge=true;state.message='CAPTCHA/challenge detected — solve it in the browser, then click RESUME.';await writeAuto(state);return;}throw new Error(result?.error||'SERP capture failed.');} if(!result.results?.length)return stopAuto('No organic SERP results detected; collection finished.');
 if(result.pageKey===state.lastPageKey)return stopAuto('SERP page did not change; collection stopped to prevent a loop.');
 const tagged=result.results.map((r,i)=>({...r,capture_id:`${Date.now()}-${state.pages}-${i}`,captured_at:new Date().toISOString()}));
 let synced=0; const uniqueAdded=[];
 for(let i=0;i<tagged.length;i+=25){const chunk=tagged.slice(i,i+25);const imported=await api('/serp/import',{method:'POST',body:JSON.stringify({token:state.token,urls:[],results:chunk,page_url:tab.url})});const fresh=Number(imported?.new_results||0);synced+=fresh;}
 const local=await readResults(); const seen=new Set(local.map(x=>x.url).filter(Boolean));
 for(const item of tagged){if(!item.url||seen.has(item.url))continue;seen.add(item.url);uniqueAdded.push(item);}
 const unique=local.concat(uniqueAdded).slice(-10000); await chrome.storage.local.set({[KEY]:unique});
 state.pages+=1;state.results=unique.length;state.lastPageKey=result.pageKey;state.message=`Page ${state.pages}: captured ${uniqueAdded.length} new unique results. Total ${state.results}.`;
 await writeAuto(state);await chrome.action.setBadgeText({text:String(Math.min(state.results,9999))});
 if(result.challengeNext){state.waitingChallenge=true;state.message='CAPTCHA/challenge detected after capture — solve it in the browser, then click RESUME.';await writeAuto(state);return;}
 if(!result.nextHref)return stopAuto(`Collection finished: ${state.pages} SERP pages, ${state.results} results.`);
 await chrome.tabs.update(state.tabId,{url:result.nextHref});
 chrome.alarms.create(ALARM,{delayInMinutes:0.03});
}

function normalizePage(url){try{const u=new URL(url);for(const k of [...u.searchParams.keys()])if(/^sca_|^sxsrf$|^ei$|^ved$|^uule$|^oq$|^sourceid$/i.test(k))u.searchParams.delete(k);return u.origin+u.pathname+'?'+u.searchParams.toString();}catch(_){return url||'';}}

async function captureSerpPage(){
 const host=location.hostname.toLowerCase(),google=host.includes('google'),text=(document.body?.innerText||'').toLowerCase();
 if(/\/sorry\//.test(location.href.toLowerCase())||/captcha|unusual traffic|verify you are human/.test(text))return{ok:false,challenge:true,error:'Search-engine challenge detected.'};
 const seen=new Set(),results=[];
 const add=(a,card)=>{if(!a)return;let u;try{u=new URL(a.getAttribute('href')||a.href,location.href);}catch(_){return;}if(!/^https?:$/.test(u.protocol)||/^(www\.)?(google|bing)\./i.test(u.hostname))return;const title=(a.querySelector('h3,h2')?.innerText||card?.querySelector('h3,h2')?.innerText||a.innerText||'').trim();if(!title)return;const snippet=(card?.querySelector('.VwiC3b,[data-sncf],div.IsZvec,.kb0PBd,.yXK7lf,.b_caption p,.b_caption,div[class*="snippet"],div[class*="caption"]')?.innerText||'').trim();let raw_text=(card?.innerText||'').trim();if(raw_text.length<snippet.length+20){let n=a;for(let i=0;i<5&&n;i++,n=n.parentElement){const t=(n.innerText||'').trim();if(t.length>raw_text.length&&t.length<5000)raw_text=t;}}const key=`${u.href}\n${title}\n${snippet}`;if(seen.has(key))return;seen.add(key);results.push({url:u.href,title,snippet,raw_text,provider:google?'google':'bing',page_url:location.href});};
 const scan=()=>{if(google){for(const a of document.querySelectorAll('a[href]:has(h3),h3 a[href],h2 a[href]'))add(a,a.closest('div.MjjYud,div.tF2Cxc'));}else{const anchors=[...document.querySelectorAll('h2 a[href],h3 a[href]')];for(const a of anchors)add(a,a.closest('li.b_algo,li,[data-bm],div'));for(const a of document.querySelectorAll('a[href]')){const t=(a.innerText||'').trim();if(t.length>15&&a.querySelector('h2,h3'))add(a,a.closest('li.b_algo,li,[data-bm],div'));}}}; let stable=0,last=-1;for(let i=0;i<40;i++){const before=results.length;scan();const h=document.documentElement.scrollHeight,bottom=scrollY+innerHeight>=h-40;if(bottom&&results.length===before)stable++;else stable=0;if(bottom&&stable>=3)break;if(h===last&&bottom)stable++;last=h;scrollTo(0,Math.min(h,scrollY+Math.max(500,Math.floor(innerHeight*.85))));await new Promise(r=>setTimeout(r,650));}scan();
 let next=null;const nextSelectors=google?['a#pnnext','a[aria-label="Next"]','a[aria-label*="Next"]']:['a.sb_pagN','a[aria-label="Next page"]','a[title="Next page"]','a[aria-label*="Next"]'];
 for(const selector of nextSelectors){const a=document.querySelector(selector);if(a?.href&&isHttp(a.href)){next=a.href;break;}}
 return{ok:true,results,pageKey:location.origin+location.pathname+'?'+new URL(location.href).searchParams.toString(),nextHref:next,challengeNext:false};
 function isHttp(u){try{return /^https?:$/i.test(new URL(u,location.href).protocol);}catch(_){return false;}}
}
