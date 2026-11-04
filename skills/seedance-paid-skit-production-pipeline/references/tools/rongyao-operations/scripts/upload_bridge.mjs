// Fixed official-page transport. Reuses the already-running dedicated Chrome.
// Never exports cookies/tokens, calls private upload functions, or replays upload HTTP.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import readline from 'node:readline';
import {CdpClient} from '../../rongyao-data-stack/scripts/active_chrome_bridge.mjs';

export const HOST = 'adopenplatform.backend.example.invalid';
export const FORM = `http://${HOST}/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video`;
export const LIST = `http://${HOST}/app/data/?_c=jrttList&_a=index&ac=jrttVideoList`;
const FIELD_NAMES = ['category_type','ai_source','origin_type','demand_name','source_ip',
                     'source_type','source_direction','gid','role','region_type','is_redbag'];
const pause = ms => new Promise(r => setTimeout(r, ms));
const failure = (status, extra={}) => ({ok:false,status,auto_retry:false,...extra});

export async function evaluate(page, expression) {
  const r=await page.send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},45000);
  if(r.exceptionDetails) throw Error('PAGE_EVALUATION_FAILED');
  return r.result?.value;
}

async function connect(stateFile) {
  const state=JSON.parse(fs.readFileSync(stateFile,'utf8'));
  if(!Number.isInteger(state.port)||state.port<1||state.port>65535) throw Error('INVALID_SESSION_PORT');
  const base=`http://127.0.0.1:${state.port}`;
  const v=await(await fetch(base+'/json/version',{signal:AbortSignal.timeout(5000)})).json();
  const u=new URL(v.webSocketDebuggerUrl);
  if(u.hostname!=='127.0.0.1'&&u.hostname!=='localhost') throw Error('NONLOCAL_SESSION');
  const browser=new CdpClient(u.href);await browser.connect();
  let id;
  try {
    id=(await browser.send('Target.createTarget',{url:'about:blank',background:true})).targetId;
    const t=(await(await fetch(base+'/json/list',{signal:AbortSignal.timeout(5000)})).json()).find(x=>x.id===id);
    const tu=new URL(t.webSocketDebuggerUrl);
    if(tu.hostname!=='127.0.0.1'&&tu.hostname!=='localhost')throw Error('NONLOCAL_SESSION');
    const page=new CdpClient(tu.href);await page.connect();await page.send('Page.enable');
    return {browser,page,id};
  }catch(e){if(id)await browser.send('Target.closeTarget',{targetId:id}).catch(()=>{});browser.close();throw e;}
}

async function httpInterstitialCount(browser) {
  if(!browser)return null;
  try{
    const result=await browser.send('Browser.getHistograms',{query:'Security.HttpsFirstMode.InterstitialReason'});
    return result.histograms.find(h=>h.name==='Security.HttpsFirstMode.InterstitialReason')?.count||0;
  }catch{return null;}
}

export async function navigate(page,url,browser=null) {
  const u=new URL(url);
  if(u.protocol!=='http:'||u.hostname!==HOST||u.port||u.username||u.password||u.pathname!=='/app/data/'||
     u.searchParams.get('_c')!=='jrttList'||u.searchParams.get('_a')!=='index'||
     !['toImgInfo','jrttVideoList'].includes(u.searchParams.get('ac'))) throw Error('NONALLOWLISTED_ENTRY');
  const before=await httpInterstitialCount(browser);
  const nav=await page.send('Page.navigate',{url});
  if(nav.errorText){
    const after=await httpInterstitialCount(browser);
    const confirmation=nav.errorText==='net::ERR_BLOCKED_BY_CLIENT'&&before!==null&&after!==null&&after>before;
    return failure(confirmation?'BROWSER_HTTP_CONFIRMATION_REQUIRED':nav.errorText==='net::ERR_BLOCKED_BY_CLIENT'?'UPLOAD_CLIENT_BLOCKED':'UPLOAD_NAVIGATION_FAILED',
      {error_code:nav.errorText,file_selected:false,upload_performed:false,
       ...(confirmation?{cause:'chrome_https_first_http_fallback',native_user_action_required:true,
         evidence:{histogram:'Security.HttpsFirstMode.InterstitialReason',before,after}}:{})});
  }
  for(let i=0;i<100;i++) {
    const s=await evaluate(page,`({host:location.hostname,ready:document.readyState,
       password:!!document.querySelector('input[type=password]'),body:!!document.body})`);
    if(s.password&&s.ready==='complete')return failure('UPLOAD_LOGIN_REQUIRED',{authenticated:false,file_selected:false,upload_performed:false});
    if(s.host===HOST&&s.ready==='complete'&&s.body)return {ok:true,authenticated:true};
    if(s.ready==='complete'&&s.host==='chromewebdata')return failure('UPLOAD_NETWORK_ERROR',{authenticated:null});
    await pause(150);
  }
  return failure('UPLOAD_ENTRY_UNVERIFIED',{authenticated:null,file_selected:false,upload_performed:false});
}

export async function readFields(page) {
  return evaluate(page,`(()=>{const out={};for(const name of ${JSON.stringify(FIELD_NAMES)}){
    if(name==='origin_type'){
      const nodes=Array.from(document.querySelectorAll('input[name="origin_type"][type="radio"]'));
      out[name]={kind:'radio',selected:nodes.filter(x=>x.checked).map(x=>x.value),
        options:nodes.map(x=>({value:x.value,label:x.parentElement.textContent.trim().slice(0,120)}))};
    }else{
      const x=document.getElementById(name);
      if(x?.tagName==='SELECT')out[name]={kind:'select',multiple:x.multiple,disabled:x.disabled,
        selected:Array.from(x.selectedOptions).map(o=>o.value),
        options:Array.from(x.options).map(o=>({value:o.value,label:o.text,disabled:o.disabled}))};
    }
  }const file=document.querySelector('input[type=file]');return {fields:out,file_input_present:!!file,
    file_input_enabled:!!file&&!file.disabled,file_selected:!!file?.files?.length,
    complete:${JSON.stringify(FIELD_NAMES)}.every(n=>out[n]?.options?.length>0||['source_ip','source_type','source_direction','role'].includes(n)&&out[n])};})()`);
}

export async function setField(page,name,value,dependent=null) {
  if(!FIELD_NAMES.includes(name))throw Error('UNKNOWN_FIELD');
  if(dependent&&!['role','source_direction'].includes(dependent))throw Error('UNKNOWN_DEPENDENCY');
  const result=await evaluate(page,`(async()=>{const name=${JSON.stringify(name)},value=${JSON.stringify(value)},dependent=${JSON.stringify(dependent)};
    if(name==='origin_type'){
      const x=Array.from(document.querySelectorAll('input[name="origin_type"][type="radio"]')).find(x=>x.value===value);
      if(!x||x.disabled)return {ok:false,status:'UNKNOWN_OPTION'};
      if(!x.checked){x.checked=true;x.dispatchEvent(new Event('input',{bubbles:true}));x.dispatchEvent(new Event('change',{bubbles:true}));}
      return {ok:true};
    }
    const x=document.getElementById(name);if(x?.tagName!=='SELECT'||x.disabled)return {ok:false,status:'MISSING_FIELD'};
    const desired=Array.isArray(value)?value:[value];
    if(desired.some(v=>!Array.from(x.options).some(o=>o.value===v&&!o.disabled)))return {ok:false,status:'UNKNOWN_OPTION'};
    if(!x.multiple&&desired.length!==1)return {ok:false,status:'INVALID_SINGLE_VALUE'};
    const prior=Array.from(x.selectedOptions).map(o=>o.value).sort();
    if(JSON.stringify(prior)!==JSON.stringify([...desired].sort())){
      let stable=null;
      if(dependent){
        const child=document.getElementById(dependent);if(!child)return {ok:false,status:'MISSING_DEPENDENCY'};
        stable=new Promise(resolve=>{let timer;const observer=new MutationObserver(()=>{
          observer.disconnect();clearTimeout(timer);resolve(true);
        });observer.observe(child,{childList:true,subtree:true});timer=setTimeout(()=>{observer.disconnect();resolve(false)},10000);});
      }
      for(const o of x.options)o.selected=desired.includes(o.value);
      x.dispatchEvent(new Event('input',{bubbles:true}));x.dispatchEvent(new Event('change',{bubbles:true}));
      if(stable&&!await stable)return {ok:false,status:'DEPENDENT_REFRESH_UNVERIFIED'};
    }return {ok:true};})()`);
  if(!result?.ok)throw Error(result?.status||'SET_FIELD_FAILED');
}

async function waitForOptions(page,name,values) {
  if(!values.length)return;
  for(let i=0;i<60;i++){
    const r=await readFields(page);
    if(values.every(v=>r.fields[name]?.options.some(o=>o.value===v&&!o.disabled)))return;
    await pause(100);
  }
  throw Error('DEPENDENT_OPTIONS_UNVERIFIED');
}

export function valuesMatch(observed,expected) {
  return FIELD_NAMES.every(name=>{
    const selected=observed.fields?.[name]?.selected;
    const desired=Array.isArray(expected[name])?expected[name]:[expected[name]];
    return selected&&JSON.stringify([...selected].sort())===JSON.stringify([...desired].sort());
  });
}

export async function applyParameters(page,values) {
  if(Object.keys(values).sort().join()!==[...FIELD_NAMES].sort().join())throw Error('ALL_FORM_FIELDS_REQUIRED');
  await setField(page,'category_type',values.category_type);
  await setField(page,'gid',values.gid,'role');
  await waitForOptions(page,'role',values.role);
  await setField(page,'source_type',values.source_type,'source_direction');
  await waitForOptions(page,'source_direction',values.source_direction);
  for(const name of FIELD_NAMES.filter(n=>!['category_type','gid','source_type'].includes(n)))
    await setField(page,name,values[name]);
  const observed=await readFields(page);
  if(!valuesMatch(observed,values)||!observed.file_input_enabled||observed.file_selected)throw Error('FORM_READBACK_MISMATCH');
  return observed;
}

export function validateListRows(records,total) {
  if(!Number.isSafeInteger(total)||total<0||!Array.isArray(records))return null;
  if(records.some(x=>!/^\d+$/.test(x.record_id||'')||typeof x.name!=='string'||!x.name.trim()))return null;
  if(new Set(records.map(x=>x.record_id)).size!==records.length)return null;
  if(records.length>total||(total>0&&records.length===0))return null;
  return records;
}

export async function readRows(page) {
  return evaluate(page,`(()=>{const table=document.querySelector('.table-responsive');if(!table)return null;
    const count=document.body.innerText.match(/视频数量为\\s*[:：]\\s*([\\d,]+)/);
    const total=count?Number(count[1].replaceAll(',','')):null;
    const ids=Array.from(table.querySelectorAll('input[name="id[]"]'));
    const records=ids.map(id=>{const card=id.closest('.col-sm-2,tr');
      const names=card?Array.from(card.querySelectorAll('input[type=text]')):[];
      const unique=card?.querySelectorAll('input[name="id[]"]').length===1;
      return {record_id:id.value,name:unique&&names.length===1?names[0].value:null};
    });
    return (${validateListRows.toString()})(records,total);})()`);
}

export async function run(action,stateFile,input,authorize) {
  if(!['fields','list','upload','probe-list'].includes(action))throw Error('INVALID_ACTION');
  const c=await connect(stateFile);let keep=false,selected=false;
  try {
    const navigateEntry=async url=>{
      const result=await navigate(c.page,url,c.browser);
      if(result.status==='BROWSER_HTTP_CONFIRMATION_REQUIRED'){
        keep=true;
        await c.browser.send('Target.activateTarget',{targetId:c.id});
        return {...result,target_id:c.id,entry_url:url,tab_preserved:true};
      }
      return result;
    };
    if(action==='probe-list'){
      const nav=await navigateEntry(LIST);
      const observation={entry:'video-list',live_check_performed:true,observed_at:new Date().toISOString()};
      if(!nav.ok)return {...nav,...observation};
      const structure=await evaluate(c.page,`({
        table:!!document.querySelector('.table-responsive'),
        search:!!document.querySelector('textarea[name=name],input[name=name]'),
        count:/视频数量为\\s*[:：]\\s*[\\d,]+/.test(document.body.innerText)
      })`);
      if(!structure?.table||!structure.search||!structure.count)return failure('LIST_STRUCTURE_CHANGED',observation);
      return {ok:true,status:'VIDEO_LIST_VERIFIED',authenticated:true,
        entry:'video-list',source:'live_official_video_list',structure,
        ...observation,surface:'existing_dedicated_chrome',
        file_selected:false,upload_performed:false};
    }
    if(action==='list'||action==='upload'){
      const name=action==='list'?input.name:input.filename;
      if(typeof name!=='string'||!name.trim())throw Error('EXPLICIT_NAME_REQUIRED');
      const u=new URL(LIST);u.searchParams.set('name',name.endsWith('.mp4')?name.slice(0,-4):name);
      const nav=await navigateEntry(u.href);if(!nav.ok)return nav;
      const records=await readRows(c.page);if(!records)return failure('LIST_STRUCTURE_CHANGED');
      if(action==='list')return {ok:true,authenticated:true,rows:records,coverage:'first_page_only',
        source:'live_backend_list',observed_at:new Date().toISOString(),upload_performed:false};
      if(records.some(x=>[input.filename,input.filename.slice(0,-4)].includes(x.name)))
        return failure('REMOTE_NAME_EXISTS_HASH_UNVERIFIED',{file_selected:false,upload_performed:false});
    }
    const nav=await navigateEntry(FORM);if(!nav.ok)return nav;
    let form=await readFields(c.page);
    if(!form.complete||!form.file_input_present)return failure('FORM_STRUCTURE_CHANGED');
    if(action==='fields'){
      if(input.gid)await setField(c.page,'gid',input.gid,'role');
      if(input.source_type?.length)await setField(c.page,'source_type',input.source_type,'source_direction');
      form=await readFields(c.page);
      return {ok:true,authenticated:true,...form,source:'live_official_form',observed_at:new Date().toISOString(),
        surface:'existing_dedicated_chrome',upload_performed:false};
    }
    if(!path.isAbsolute(input.file)||path.basename(input.file)!==input.filename||!fs.statSync(input.file).isFile())throw Error('INVALID_UPLOAD_FILE');
    form=await applyParameters(c.page,input.parameters);
    if(!await authorize())return failure('SELECTION_CHECKPOINT_NOT_COMMITTED',{file_selected:false,upload_performed:false});
    // Preserve the tab from this point: a connection failure may leave an in-flight upload.
    keep=true;selected=true;
    const root=await c.page.send('DOM.getDocument');
    const q=await c.page.send('DOM.querySelector',{nodeId:root.root.nodeId,selector:'input[type=file]'});
    if(!q.nodeId)throw Error('FILE_INPUT_DISAPPEARED');
    await c.page.send('DOM.setFileInputFiles',{nodeId:q.nodeId,files:[input.file]},45000);
    const selectedName=await evaluate(c.page,`Array.from(document.querySelector('input[type=file]').files).map(x=>x.name)`);
    if(selectedName.length!==1||selectedName[0]!==input.filename)throw Error('FILE_SELECTION_UNVERIFIED');
    return {ok:true,status:'FILE_SELECTED_PENDING_BACKEND',file_selected:true,upload_attempted:true,
      upload_performed:null,listed_verified:false,metadata_verified:false,target_id:c.id,
      form_values:input.parameters,sha256:input.sha256,next_step:'Run job reconcile after the page processing interval.'};
  }catch(e){
    return failure(selected?'SUBMISSION_UNKNOWN':String(e.message).match(/^[A-Z_]+$/)?e.message:'UPLOAD_TOOL_ERROR',
      {file_selected:selected?null:false,upload_performed:selected?null:false,target_id:keep?c.id:null});
  }finally{
    c.page.close();if(!keep)await c.browser.send('Target.closeTarget',{targetId:c.id}).catch(()=>{});c.browser.close();
  }
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
  const [action,stateFile,inputFile]=process.argv.slice(2);
  const rl=readline.createInterface({input:process.stdin});
  let answer;
  rl.on('line',line=>{answer=line;});
  const authorize=async()=>{
    console.log(JSON.stringify({event:'before_file_selection'}));
    for(let i=0;i<100&&answer===undefined;i++)await pause(100);
    return answer==='SELECT';
  };
  try {
    const result=await run(action,stateFile,JSON.parse(fs.readFileSync(inputFile,'utf8')),authorize);
    console.log(JSON.stringify({event:'result',result}));
  }catch(e){console.log(JSON.stringify({event:'result',result:failure('UPLOAD_TOOL_ERROR')}));process.exitCode=1;}
  finally {rl.close();}
}
