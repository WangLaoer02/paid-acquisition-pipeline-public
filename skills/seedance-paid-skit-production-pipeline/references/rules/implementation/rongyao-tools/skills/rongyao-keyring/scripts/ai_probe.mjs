// Fixed AI-entry authentication, using the existing Chrome and fixed Keychain worker.
// No credential output, cookie export, model submission, or browser security changes.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {CdpClient} from '../../rongyao-data-stack/scripts/active_chrome_bridge.mjs';
import {evaluate} from '../../rongyao-operations/scripts/upload_bridge.mjs';
import {loginPortal,followPortalEntry} from './upload_probe.mjs';
const AI='ai.cn.sy.backend.example.invalid', POWER='power.houtai.backend.example.invalid';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const fail=(status,extra={})=>({ok:false,status,entry:'ai',authenticated:false,auto_retry:false,generation_performed:false,...extra});
export function safeDiagnostic(error,phase){
 const code=String(error?.cause?.code||error?.code||'');
 const safe=['ECONNREFUSED','ECONNRESET','ETIMEDOUT','ENOTFOUND','EPIPE','ENOENT'].includes(code)?code:'UNCLASSIFIED_TOOL_ERROR';
 return fail('AI_ENTRY_TOOL_OR_NETWORK_ERROR',{phase,error_code:safe});
}
export function holdPriorAuthentication(prior,state){
 return prior?.pid===state.pid&&['LOGIN_SUBMISSION_PENDING','LOGIN_PENDING_TIMEOUT','LOGIN_REJECTED','LOGIN_OR_VERIFICATION_REQUIRED'].includes(prior?.status);
}
function authRecord(file,value){
 const temp=file+'.tmp';fs.writeFileSync(temp,JSON.stringify(value),{mode:0o600});fs.renameSync(temp,file);
}

export async function protectedAiRead(page){
 return evaluate(page,`(async()=>{if(location.hostname!==${JSON.stringify(AI)}||!window.AI_MODEL_OPTIONS_BY_TYPE)return {ok:false,status:'AI_PAGE_NOT_READY'};try{const r=await fetch('/data/?_c=aiModel&_a=quotaSummary&mode=video&detail=1',{credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(15000)});if(!r.ok)return {ok:false,status:'AI_PROTECTED_READ_FAILED'};let p;try{p=JSON.parse(await r.text())}catch{return {ok:false,status:'AI_NON_JSON_RESPONSE'}};if(p.ok!==true||!p.data)return {ok:false,status:'AI_PROTECTED_READ_REJECTED'};const f=(p.data.features||[]).find(x=>x.quota_feature==='ai_video');return {ok:true,quota:f?{meter_type:f.meter_type,is_exceeded:f.is_exceeded,periods:f.periods}:null}}catch{return {ok:false,status:'AI_PROTECTED_READ_TOOL_OR_NETWORK_ERROR'}}})()`);
}
export async function verifyAi(stateFile){
 const state=JSON.parse(fs.readFileSync(stateFile,'utf8'));
 const journal=stateFile+'.ai-auth.json';
 let prior;try{prior=JSON.parse(fs.readFileSync(journal,'utf8'))}catch(error){if(error.code!=='ENOENT')return fail('AI_AUTH_CHECKPOINT_INVALID',{phase:'authentication_checkpoint'});}
 let phase='devtools_discovery';
 if(!Number.isInteger(state.port))throw Error('INVALID_SESSION_PORT');
 const base=`http://127.0.0.1:${state.port}`;
 const version=await(await fetch(base+'/json/version',{signal:AbortSignal.timeout(5000)})).json();
 const socket=new URL(version.webSocketDebuggerUrl);
 if(!['127.0.0.1','localhost'].includes(socket.hostname))throw Error('NONLOCAL_SESSION');
 const browser=new CdpClient(socket.href);await browser.connect();let page,id,keep=false,passwordSubmitted=false;
 const clearAuth=()=>{try{fs.unlinkSync(journal)}catch{}};
 try{
  const tabs=await(await fetch(base+'/json/list')).json();
  const existing=tabs.filter(t=>t.type==='page'&&new URL(t.url).origin===`http://${AI}`);
  if(existing.length>1)return fail('MULTIPLE_AI_TABS',{phase:'devtools_discovery'});
  if(existing.length){
   const target=existing[0];id=target.id;keep=true;page=new CdpClient(target.webSocketDebuggerUrl);await page.connect();
   phase='protected_read';const result=await protectedAiRead(page);
   if(!result.ok)return {...fail(result.status),target_id:id,tab_preserved:true};
   clearAuth();return {ok:true,status:'AI_ENTRY_ACCESS_VERIFIED',entry:'ai',authenticated:true,auth_method:'existing_session',password_submitted:false,account_identity_verified:false,generation_performed:false,port:state.port,target_id:id,quota:result.quota};
  }
  // A delayed login may have completed in an existing portal target. Reuse it
  // before considering any password submission; never require a front window.
  for(const target of tabs.filter(t=>t.type==='page'&&new URL(t.url).hostname===POWER)){
   const portal=new CdpClient(target.webSocketDebuggerUrl);await portal.connect();
   const ready=await evaluate(portal,`location.hostname===${JSON.stringify(POWER)}&&!document.querySelector('input[type=password]')&&[...document.querySelectorAll('a[href]')].filter(a=>a.hostname===${JSON.stringify(AI)}).length===1`);
   if(!ready){portal.close();continue}
   page=portal;id=target.id;keep=true;phase='portal_navigation';
   const nav=await followPortalEntry(page,AI);if(!nav.ok)return {...nav,entry:'ai',phase,target_id:id,tab_preserved:true};
   phase='protected_read';const result=await protectedAiRead(page);
   if(!result.ok)return {...fail(result.status),phase,target_id:id,tab_preserved:true};
   clearAuth();return {ok:true,status:'AI_ENTRY_ACCESS_VERIFIED',entry:'ai',authenticated:true,auth_method:'existing_portal_session',password_submitted:false,account_identity_verified:false,generation_performed:false,port:state.port,target_id:id,quota:result.quota};
  }
  if(holdPriorAuthentication(prior,state))return fail(prior.status,{phase:'prior_authentication_pending',prior_password_submitted:true,target_id:prior.target_id,tab_preserved:true});
  phase='navigation';
  id=(await browser.send('Target.createTarget',{url:'about:blank',background:true})).targetId;
  const target=(await(await fetch(base+'/json/list')).json()).find(t=>t.id===id);
  page=new CdpClient(target.webSocketDebuggerUrl);await page.connect();await page.send('Page.enable');
  const nav=await page.send('Page.navigate',{url:`http://${AI}/data/`});
  if(nav.errorText){keep=true;return {...fail('AI_BROWSER_NAVIGATION_BLOCKED'),target_id:id,tab_preserved:true,native_user_action_required:true};}
  let observed;
  for(let i=0;i<100;i++){
   try{observed=await evaluate(page,`({host:location.hostname,ready:document.readyState,password:!!document.querySelector('input[type=password]'),model_config:!!window.AI_MODEL_OPTIONS_BY_TYPE})`)}catch{observed={ready:'loading'}}
   if(observed.ready==='complete'&&((observed.host===AI&&observed.model_config)||observed.host===POWER))break;
   await pause(150);
  }
  if(observed?.host===POWER){
   phase='portal_authentication';
   const auth=observed.password?await loginPortal(page,{username:process.env.RONGYAO_USERNAME,password:process.env.RONGYAO_PASSWORD},pause,AI,async()=>authRecord(journal,{pid:state.pid,target_id:id,status:'LOGIN_SUBMISSION_PENDING'})):await followPortalEntry(page,AI);
   passwordSubmitted=auth.password_submitted===true;
   if(!auth.ok){keep=true;if(auth.password_submitted)authRecord(journal,{pid:state.pid,target_id:id,status:auth.status});return {...auth,entry:'ai',phase,generation_performed:false,target_id:id,tab_preserved:true};}
  }
  for(let i=0;i<50;i++){
   const ready=await evaluate(page,`location.hostname===${JSON.stringify(AI)}&&!!window.AI_MODEL_OPTIONS_BY_TYPE`);
   if(ready)break;await pause(150);
  }
  phase='protected_read';const result=await protectedAiRead(page);
  keep=true;
  if(!result.ok)return {...fail(result.status),target_id:id,tab_preserved:true};
  clearAuth();return {ok:true,status:'AI_ENTRY_ACCESS_VERIFIED',entry:'ai',authenticated:true,auth_method:passwordSubmitted?'password_login_via_native_portal':'existing_portal_session',password_submitted:passwordSubmitted,account_identity_verified:false,generation_performed:false,port:state.port,target_id:id,quota:result.quota};
 }catch(error){keep=!!id;return {...safeDiagnostic(error,phase),target_id:id,tab_preserved:keep};}finally{
  page?.close();if(id&&!keep)await browser.send('Target.closeTarget',{targetId:id}).catch(()=>{});browser.close();
 }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
 try{const r=await verifyAi(process.argv[2]);console.log(JSON.stringify(r));process.exitCode=r.ok?0:1}
 catch(error){console.log(JSON.stringify(safeDiagnostic(error,'session_setup')));process.exitCode=1}
}
