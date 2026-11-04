import test from 'node:test';
import assert from 'node:assert/strict';
import {holdPriorAuthentication,safeDiagnostic} from './ai_probe.mjs';
import {loginPortal} from './upload_probe.mjs';
test('pending or rejected login cannot resubmit in same session',()=>{
 for(const status of ['LOGIN_SUBMISSION_PENDING','LOGIN_PENDING_TIMEOUT','LOGIN_REJECTED','LOGIN_OR_VERIFICATION_REQUIRED'])
  assert.equal(holdPriorAuthentication({pid:12,status},{pid:12}),true);
 assert.equal(holdPriorAuthentication({pid:12,status:'LOGIN_PENDING_TIMEOUT'},{pid:13}),false);
});
test('error classification preserves stage without leaking error text',()=>{
 const r=safeDiagnostic({message:'fixture-secret https://private.invalid',cause:{code:'ECONNREFUSED'}},'devtools_discovery');
 assert.equal(r.error_code,'ECONNREFUSED');assert.equal(r.phase,'devtools_discovery');
 assert.ok(!JSON.stringify(r).includes('fixture-secret'));assert.ok(!JSON.stringify(r).includes('private.invalid'));
});
test('authentication checkpoint precedes the one submit',async()=>{
 let index=0,checkpoint=false,submits=0;
 const values=[{host:'power.houtai.backend.example.invalid',normal:true},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:true,links:0}];
 const page={send:async(method,args)=>{
  if(args.expression.includes("document.querySelector('#submit').click()")){assert.equal(checkpoint,true);submits++;}
  return {result:{value:values[Math.min(index++,values.length-1)]}};
 }};
 const r=await loginPortal(page,{username:'fixture',password:'fixture-secret'},async()=>{},'ai.cn.sy.backend.example.invalid',async()=>{checkpoint=true;});
 assert.equal(r.status,'LOGIN_PENDING_TIMEOUT');assert.equal(submits,1);
});
