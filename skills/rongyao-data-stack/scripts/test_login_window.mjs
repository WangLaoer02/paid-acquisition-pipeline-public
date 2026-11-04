import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { CdpClient, queryData, exportData, finishCaptureTarget, showLogin } from './active_chrome_bridge.mjs';

for (const silent of [false, true]) for (const method of ['query', 'export']) {
  for (const reason of ['redirect', 'fetch-login', 'other-error']) {
    test(`${method}: ${reason}, background=${silent}, keeps only requested login targets and never replays`, async () => {
      const folder=fs.mkdtempSync(path.join(os.tmpdir(),'login-target-test-'));
      const state=path.join(folder,'state.json'); const request=path.join(folder,'request.json');
      fs.writeFileSync(state,JSON.stringify({port:1234,pid:process.pid}));fs.writeFileSync(request,JSON.stringify({requests:[]}));
      const fetchBefore=globalThis.fetch;const originals=Object.fromEntries(['send','connect','close'].map(k=>[k,CdpClient.prototype[k]]));
      const calls=[];let submissions=0;
      const savedBackground=process.env.RONGYAO_CAPTURE_BACKGROUND;
      if(silent) process.env.RONGYAO_CAPTURE_BACKGROUND='1'; else delete process.env.RONGYAO_CAPTURE_BACKGROUND;
      globalThis.fetch=async(url)=>({ok:true,json:async()=>url.endsWith('/json/version')?{webSocketDebuggerUrl:'ws://fixture/browser'}:[{id:'test',type:'page',url:'http://power.houtai.backend.example.invalid/',webSocketDebuggerUrl:'ws://fixture/page'}]});
      CdpClient.prototype.connect=async()=>{};
      CdpClient.prototype.close=function(){calls.push('disconnect:'+this.url)};
      CdpClient.prototype.send=async function(method,params={}) {
        calls.push(method);
        if(method==='Target.createTarget'){ assert.equal(params.background,true);assert.equal(params.newWindow,false);assert.equal(params.hidden,undefined);return {targetId:'test'};}
        if(method==='Browser.getWindowForTarget')return {windowId:1};
        if(method==='Runtime.evaluate'){
          if(params.expression.includes('ready:document.readyState'))return {result:{value:reason==='redirect'?{href:'http://power.houtai.backend.example.invalid/',host:'power.houtai.backend.example.invalid',ready:'complete'}:{href:'http://data.houtai.cn.sy.backend.example.invalid/market/',host:'data.houtai.cn.sy.backend.example.invalid',ready:'complete'}}};
          if(params.expression==='location.href')return {result:{value:'http://power.houtai.backend.example.invalid/'}};
          if(params.awaitPromise){submissions++;return {exceptionDetails:{text:reason==='fetch-login'?'LOGIN_REQUIRED':'PAGE_CONFIG_CHANGED'}};}
        }
        return {};
      };
      try{
        const options={'state-file':state,'request-file':request,output:path.join(folder,'out.csv'),'date-range':'2026/08/01-2026/08/31','material-range':'2023/01/01-2026/09/06',gid:'193'};
        await assert.rejects((method==='query'?queryData:exportData)(options),reason==='other-error'?/PAGE_CONFIG_CHANGED/:/LOGIN_REQUIRED/);
        assert.equal(calls.includes('Target.closeTarget'),silent||reason==='other-error');
        assert.equal(calls.includes('Target.activateTarget'),!silent&&reason!=='other-error');
        assert.equal(submissions,reason==='redirect'?0:1);
        assert.ok(calls.includes('disconnect:ws://fixture/page'));assert.ok(calls.includes('disconnect:ws://fixture/browser'));
        assert.equal(fs.existsSync(options.output),false);
      }finally{
        if(savedBackground===undefined) delete process.env.RONGYAO_CAPTURE_BACKGROUND;else process.env.RONGYAO_CAPTURE_BACKGROUND=savedBackground;
        globalThis.fetch=fetchBefore;Object.assign(CdpClient.prototype,originals);fs.rmSync(folder,{recursive:true,force:true});
      }
    });
  }
}
test('successful capture closes its temporary target',async()=>{
  const calls=[];const browser={send:async(m)=>{calls.push(m);return{}},close(){calls.push('browser-disconnect')}};
  const page={send:async()=>({}),close(){calls.push('page-disconnect')}};
  await finishCaptureTarget(browser,page,'capture-id','cache',false);
  assert.ok(calls.includes('Target.closeTarget'));assert.ok(!calls.includes('Target.activateTarget'));
});
test('login detected by fetch navigates only the backend page, then restores its window',async()=>{
  const calls=[];const browser={send:async(m,p)=>{calls.push([m,p]);return{windowId:4}},close(){}};
  const page={send:async(m,p)=>{calls.push([m,p]);return {result:{value:'http://data.houtai.cn.sy.backend.example.invalid/market/'}}},close(){}};
  await finishCaptureTarget(browser,page,'login-id','cache',true);
  assert.equal(calls.find(([m])=>m==='Page.navigate')[1].url,'http://power.houtai.backend.example.invalid/');
  assert.equal(calls.find(([m])=>m==='Browser.setWindowBounds')[1].bounds.windowState,'normal');
  assert.ok(!calls.some(([m])=>m==='Target.closeTarget'));
});

test('background capture with no browser window stops before query and disconnects', async()=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'background-no-window-'));
  const state=path.join(folder,'state.json');fs.writeFileSync(state,JSON.stringify({port:1234,pid:process.pid}));
  const before=globalThis.fetch, env=process.env.RONGYAO_CAPTURE_BACKGROUND;
  const originals=Object.fromEntries(['send','connect','close'].map(k=>[k,CdpClient.prototype[k]]));const calls=[];
  process.env.RONGYAO_CAPTURE_BACKGROUND='1';
  globalThis.fetch=async(url)=>({ok:true,json:async()=>url.endsWith('/json/list')?[]:{webSocketDebuggerUrl:'ws://fixture/browser'}});
  CdpClient.prototype.connect=async()=>{};CdpClient.prototype.close=()=>calls.push('disconnect');
  CdpClient.prototype.send=async function(m){calls.push(m);throw new Error('Failed to open new tab - no browser is open')};
  try {
    await assert.rejects(exportData({'state-file':state,output:path.join(folder,'out.csv'),'date-range':'2026/08/01-2026/08/31','material-range':'2026/08/01-2026/08/31',gid:'193'}),/LOGIN_REQUIRED/);
    assert.deepEqual(calls,['Target.createTarget','disconnect']);
  } finally {globalThis.fetch=before;Object.assign(CdpClient.prototype,originals);if(env===undefined)delete process.env.RONGYAO_CAPTURE_BACKGROUND;else process.env.RONGYAO_CAPTURE_BACKGROUND=env;fs.rmSync(folder,{recursive:true,force:true});}
});
