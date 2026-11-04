// Fixed same-profile upload authentication. Credentials only arrive through the Keychain worker environment.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {CdpClient} from '../../rongyao-data-stack/scripts/active_chrome_bridge.mjs';
import {navigate,evaluate,FORM,HOST} from '../../rongyao-operations/scripts/upload_bridge.mjs';
const POWER='power.houtai.backend.example.invalid';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const fail=(status,extra={})=>({ok:false,status,auto_retry:false,authenticated:false,file_selected:false,upload_performed:false,...extra});
export async function followPortalEntry(page,entryHost=HOST,delay=pause){
 if(![HOST,'ai.cn.sy.backend.example.invalid'].includes(entryHost))return fail('NONALLOWLISTED_ENTRY');
 const clicked=await evaluate(page,`(()=>{if(location.hostname!==${JSON.stringify(POWER)}||document.querySelector('input[type=password]'))return false;const links=[...document.querySelectorAll('a[href]')].filter(a=>a.hostname===${JSON.stringify(entryHost)}&&['http:','https:'].includes(a.protocol));if(links.length!==1)return false;links[0].target='_self';links[0].click();return true})()`);
 if(!clicked)return fail('UPLOAD_PORTAL_ENTRY_UNVERIFIED');
 for(let i=0;i<80;i++){
  const s=await evaluate(page,`({host:location.hostname,ready:document.readyState,password:!!document.querySelector('input[type=password]')})`);
  if(s?.host===entryHost&&s.ready==='complete'&&!s.password)return {ok:true};
  if(s?.ready==='complete'&&s.password)return fail('UPLOAD_LOGIN_OR_PERMISSION_REQUIRED');
  await delay(150);
 }
 return fail('UPLOAD_PORTAL_NAVIGATION_UNVERIFIED');
}
export async function loginPortal(page,credentials,delay=pause,entryHost=HOST,beforeSubmit=async()=>{}){
 if(![HOST,'ai.cn.sy.backend.example.invalid'].includes(entryHost))return fail('NONALLOWLISTED_ENTRY');
 const form=await evaluate(page,`(()=>{const p=document.querySelector('#password'),u=document.querySelector('#username'),s=document.querySelector('#submit');return {host:location.hostname,normal:!!p&&p.type==='password'&&!!u&&!!s&&p.form===u.form,challenge:[...document.querySelectorAll('input')].some(x=>/captcha|verification|sms|otp|(?:^| )code(?: |$)/i.test(x.name+' '+x.id)&&!!x.getClientRects().length)}})()`);
 if(form?.host!==POWER||!form.normal)return fail('UPLOAD_LOGIN_FORM_UNVERIFIED');
 if(form.challenge)return fail('LOGIN_OR_VERIFICATION_REQUIRED');
 if(!credentials?.username||!credentials?.password)return fail('CREDENTIALS_NOT_CONFIGURED');
 await beforeSubmit();
 await evaluate(page,`(()=>{const u=document.querySelector('#username'),p=document.querySelector('#password');u.value=${JSON.stringify(credentials.username)};p.value=${JSON.stringify(credentials.password)};for(const x of [u,p]){x.dispatchEvent(new Event('input',{bubbles:true}));x.dispatchEvent(new Event('change',{bubbles:true}));}document.querySelector('#submit').click();return true})()`);
 // One submission only. Keep a rejected or challenged form for the owner.
 await delay(1500);
 let state;
 for(let i=0;i<80;i++){
  state=await evaluate(page,`(()=>{const visible=e=>!!e.getClientRects().length;const errors=[...document.querySelectorAll('.error,.alert-danger,.layui-layer-dialog,.layui-layer-msg,[role=alert],#error,.error-message')].filter(visible).map(e=>e.textContent||'').join(' ');return {ready:document.readyState,host:location.hostname,password:!!document.querySelector('input[type=password]'),links:[...document.querySelectorAll('a[href]')].filter(a=>a.hostname===${JSON.stringify(entryHost)}).length,challenge:[...document.querySelectorAll('input')].some(e=>/captcha|verification|sms|otp|(?:^| )code(?: |$)/i.test(e.name+' '+e.id)&&visible(e)),rejected:/(?:密码|账号|账户).{0,12}(?:错误|不正确|不存在|禁用|锁定)|(?:password|account).{0,20}(?:incorrect|invalid|locked|disabled)/i.test(errors)}})()`);
  if(state?.ready==='complete'&&(state.challenge||state.rejected||state.host!==POWER||(!state.password&&state.links)))break;
  await delay(150);
 }
 if(state?.challenge)return fail('LOGIN_OR_VERIFICATION_REQUIRED',{password_submitted:true});
 if(state?.rejected)return fail('LOGIN_REJECTED',{password_submitted:true});
 if(state?.password)return fail('LOGIN_PENDING_TIMEOUT',{password_submitted:true});
 if(state?.host===entryHost)return {ok:true,password_submitted:true};
 if(state?.host!==POWER||state.links!==1)return fail('UPLOAD_PORTAL_ENTRY_UNVERIFIED',{password_submitted:true,portal_entry_count:state?.links||0});
 return {...await followPortalEntry(page,entryHost,delay),password_submitted:true};
}
export async function verifyUpload(stateFile){
 const state=JSON.parse(fs.readFileSync(stateFile,'utf8'));if(!Number.isInteger(state.port))throw Error('INVALID_SESSION_PORT');
 const base=`http://127.0.0.1:${state.port}`;
 const v=await(await fetch(base+'/json/version',{signal:AbortSignal.timeout(5000)})).json();
 const u=new URL(v.webSocketDebuggerUrl);if(!['127.0.0.1','localhost'].includes(u.hostname))throw Error('NONLOCAL_SESSION');
 const browser=new CdpClient(u.href);await browser.connect();let page,id,keep=false,passwordSubmitted=false;
 try{
  id=(await browser.send('Target.createTarget',{url:'about:blank',background:true})).targetId;
  const target=(await(await fetch(base+'/json/list')).json()).find(x=>x.id===id);
  page=new CdpClient(target.webSocketDebuggerUrl);await page.connect();await page.send('Page.enable');
  let nav=await navigate(page,FORM,browser);
  if(nav.status==='UPLOAD_LOGIN_REQUIRED'){
   const auth=await loginPortal(page,{username:process.env.RONGYAO_USERNAME,password:process.env.RONGYAO_PASSWORD});
   passwordSubmitted=auth.password_submitted===true;
   if(!auth.ok){keep=true;return {...auth,target_id:id,tab_preserved:true};}
   nav=await navigate(page,FORM,browser);
  }
  if(!nav.ok){keep=['BROWSER_HTTP_CONFIRMATION_REQUIRED','UPLOAD_LOGIN_REQUIRED'].includes(nav.status);return {...nav,target_id:keep?id:null,tab_preserved:keep};}
  const fields=await evaluate(page,`({host:location.hostname,file:!!document.querySelector('input[type=file]'),fields:['category_type','ai_source','origin_type','demand_name','gid','role','region_type'].filter(n=>document.querySelector('[name="'+n+'"],#'+n)),password:!!document.querySelector('input[type=password]')})`);
  if(fields?.host!==HOST||!fields.file||fields.password||fields.fields.length!==7)return fail('UPLOAD_FORM_STRUCTURE_CHANGED');
  return {ok:true,status:'UPLOAD_FORM_ACCESS_VERIFIED',entry:'upload',surface:'dedicated_chrome',authenticated:true,auth_method:passwordSubmitted?'password_login_via_native_portal':'existing_session',password_submitted:passwordSubmitted,file_input_present:true,file_selected:false,upload_performed:false,account_identity_verified:false,observed_at:new Date().toISOString()};
 }finally{
  if(keep&&id)await browser.send('Target.activateTarget',{targetId:id}).catch(()=>{});
  page?.close();if(id&&!keep)await browser.send('Target.closeTarget',{targetId:id}).catch(()=>{});browser.close();
 }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
 try{const result=await verifyUpload(process.argv[2]);console.log(JSON.stringify(result));process.exitCode=result.ok?0:1;}
 catch{console.log(JSON.stringify(fail('UPLOAD_ENTRY_TOOL_OR_NETWORK_ERROR')));process.exitCode=1;}
}
