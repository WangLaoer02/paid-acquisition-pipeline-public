#!/usr/bin/env node
// Same-profile access; credentials stay inside this process and Chrome.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {CdpClient} from './active_chrome_bridge.mjs';

const DATA = 'data.houtai.cn.sy.backend.example.invalid';
const POWER = 'power.houtai.backend.example.invalid';
const DEMAND = 'demand.backend.example.invalid';
export function validateDetail(value) {
  const u = new URL(value);
  if (!['http:', 'https:'].includes(u.protocol) || u.hostname !== DEMAND || u.port || u.username || u.password || u.pathname !== '/data/' ||
      u.searchParams.get('_c') !== 'creativeVideoList' || u.searchParams.get('_a') !== 'index' || u.searchParams.get('ac') !== 'openVideo') throw Error('INVALID_DETAIL_URL');
  return value;
}

async function connect(stateFile) {
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  const base = `http://127.0.0.1:${Number(state.port)}`;
  const version = await (await fetch(base + '/json/version', {signal:AbortSignal.timeout(5000)})).json();
  const browser = new CdpClient(version.webSocketDebuggerUrl); await browser.connect();
  const created = await browser.send('Target.createTarget', {url:'about:blank', background:true});
  try {
    const targets = await (await fetch(base + '/json/list')).json();
    const target = targets.find(x => x.id === created.targetId);
    const page = new CdpClient(target.webSocketDebuggerUrl); await page.connect();
    return {browser, page, id:created.targetId};
  } catch(e) { await browser.send('Target.closeTarget', {targetId:created.targetId}); browser.close(); throw e; }
}
async function evaluate(page, expression) {
  const r = await page.send('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true}, 35000);
  if (r.exceptionDetails) throw Error('PAGE_EVALUATION_FAILED');
  return r.result?.value;
}
async function navigate(page, url) {
  await page.send('Page.enable');
  const before=(await page.send('Page.getFrameTree')).frameTree.frame.loaderId;
  await page.send('Page.navigate', {url});
  for(let i=0;i<100;i++) {
    const loader=(await page.send('Page.getFrameTree')).frameTree.frame.loaderId;
    const s=await evaluate(page, '({host:location.hostname,ready:document.readyState,body:!!document.body})');
    if(loader!==before && s.host && s.ready==='complete' && s.body) return s;
    await new Promise(r=>setTimeout(r,200));
  }
  throw Error('PAGE_LOAD_TIMEOUT');
}
export async function prepare(stateFile, forceLogin=false) {
  if(forceLogin && (!process.env.RONGYAO_USERNAME || !process.env.RONGYAO_PASSWORD)) throw Error('CREDENTIALS_NOT_CONFIGURED');
  const c=await connect(stateFile);
  let keepLoginPage=false;
  let passwordSubmitted=false;
  let keepAuthenticatedPage=false;
  try {
    // Verify the account portal first: a market-domain cookie can outlive logout.
    let s=await navigate(c.page, `http://${POWER}/`);
    if(forceLogin && s.host===POWER) {
      const logout=await evaluate(c.page, `Array.from(document.querySelectorAll('a')).find(a=>a.textContent.trim()==='退出'&&a.getAttribute('href')==='/?_c=login&_a=loginout')?.href||null`);
      if(logout) s=await navigate(c.page, logout);
    }
    if(s.host===POWER) {
      const form=await evaluate(c.page, `({password:!!document.querySelector('input[type=password]'),portal:!!Array.from(document.querySelectorAll('a')).find(a=>a.hostname===${JSON.stringify(DATA)})})`);
      if(form.password) {
        const user=process.env.RONGYAO_USERNAME, password=process.env.RONGYAO_PASSWORD;
        if(!user || !password) return {ok:false,authenticated:false,status:'LOGIN_REQUIRED',credentialConfigured:false};
        // One normal login submission. Never request SMS, solve MFA, or retry a rejection.
        await evaluate(c.page, `(()=>{document.querySelector('#username').value=${JSON.stringify(user)};document.querySelector('input[type=password]').value=${JSON.stringify(password)};document.querySelector('#submit').click();return true;})()`);
        passwordSubmitted=true;
        await new Promise(r=>setTimeout(r,2000));
        const remains=await evaluate(c.page, "!!document.querySelector('input[type=password]')");
        if(remains) {
          keepLoginPage=true;
          return {ok:false,authenticated:false,status:'LOGIN_OR_VERIFICATION_REQUIRED',credentialConfigured:true};
        }
      } else if(!form.portal) return {ok:false,authenticated:false,status:'LOGIN_REQUIRED'};
      s=await navigate(c.page, `http://${DATA}/market/`);
    }
    if(s.host!==DATA) return {ok:false,authenticated:false,status:'LOGIN_REQUIRED'};
    const verified=await evaluate(c.page, `(async()=>{const r=await fetch('/marketng/?_c=adopenplatformSource&_a=index',{credentials:'include',signal:AbortSignal.timeout(20000)});const h=await r.text();const ok=r.ok&&new URL(r.url).hostname===${JSON.stringify(DATA)}&&h.includes('_pageConfig');return {ok,authenticated:ok,status:ok?'authenticated':'LOGIN_REQUIRED'};})()`);
    if(forceLogin && !passwordSubmitted) return {ok:false,authenticated:false,status:'PASSWORD_SUBMISSION_NOT_VERIFIED'};
    keepAuthenticatedPage=verified.ok && process.env.RONGYAO_KEEP_AUTHENTICATED_PAGE==='1';
    return {...verified,auth_method:passwordSubmitted?'password_login':'existing_session',password_submitted:passwordSubmitted,...(keepAuthenticatedPage?{captureTargetId:c.id}:{})};
  } finally {
    if(keepLoginPage) {
      await c.browser.send('Target.activateTarget',{targetId:c.id}).catch(()=>{});
      await c.page.send('Page.bringToFront').catch(()=>{});
    } else if(!keepAuthenticatedPage) await c.browser.send('Target.closeTarget',{targetId:c.id}).catch(()=>{});
    c.page.close();c.browser.close();
  }
}
export async function resolve(stateFile, url) {
  validateDetail(url);
  const c=await connect(stateFile);
  try {
    const s=await navigate(c.page,url);
    if(s.host!==DEMAND) return {ok:false,status:'LOGIN_REQUIRED',demand_url:url};
    const r=await evaluate(c.page, `(()=>{const root=document.querySelector('.video');return {title:document.querySelector('.video_title')?.textContent.trim()||null,media:root?Array.from(root.querySelectorAll('img[name],video,source')).map(x=>({url:x.getAttribute('name')||x.currentSrc||x.src,cover:x.tagName==='IMG'?x.src:null})):[]};})()`);
    const media=r.media.filter(x=>{try {const u=new URL(x.url);return ['http:','https:'].includes(u.protocol)&&u.hostname==='market-sy-ad-static.backend.example.invalid'&&/\.mp4$/i.test(u.pathname);}catch{return false;}});
    return {ok:media.length>0,status:media.length?'resolved':'VIDEO_NOT_FOUND',demand_url:url,title:r.title,media,source_extracted:media.length>0,page_accessible:true,video_playable:null,transcript:null};
  } finally {c.page.close();await c.browser.send('Target.closeTarget',{targetId:c.id}).catch(()=>{});c.browser.close();}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  const [cmd,state,url]=process.argv.slice(2);
  try {console.log(JSON.stringify(await (cmd==='prepare'?prepare(state):cmd==='relogin'?prepare(state,true):cmd==='resolve'?resolve(state,url):Promise.reject(Error('INVALID_COMMAND')))));}
  catch(e) {console.log(JSON.stringify({ok:false,status:String(e.message).replace(/https?:\/\/\S+/g,'[url]').slice(0,200)}));process.exitCode=1;}
}
