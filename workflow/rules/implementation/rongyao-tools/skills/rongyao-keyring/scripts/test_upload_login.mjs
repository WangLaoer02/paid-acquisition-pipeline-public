import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {loginPortal} from './upload_probe.mjs';
const credentials={username:'fixture-user',password:'fixture-secret'};
function page(values){let n=0;const expressions=[];return {expressions,send:async(method,args)=>{assert.equal(method,'Runtime.evaluate');expressions.push(args.expression);return {result:{value:values[Math.min(n++,values.length-1)]}};}};}
test('wrong-host login form never receives credentials',async()=>{const p=page([{host:'example.com',normal:true}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.status,'UPLOAD_LOGIN_FORM_UNVERIFIED');assert.equal(p.expressions.length,1);assert.ok(!p.expressions[0].includes('fixture-secret'));});
test('a visible challenge stops before normal login submission',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true,challenge:true}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.status,'LOGIN_OR_VERIFICATION_REQUIRED');assert.equal(p.expressions.length,1);});
test('rejected normal login is submitted once and not retried',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true,challenge:false},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:true,links:0,rejected:true}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.status,'LOGIN_REJECTED');assert.equal(p.expressions.filter(x=>x.includes("document.querySelector('#submit').click()")).length,1);assert.ok(!JSON.stringify(r).includes('fixture-secret'));});
test('successful login follows the existing portal link without exporting its URL',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true,challenge:false},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:false,links:1},true,{host:'adopenplatform.backend.example.invalid',ready:'complete',password:false}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.ok,true);assert.equal(r.password_submitted,true);assert.ok(p.expressions[3].includes("links[0].target='_self';links[0].click()"));assert.deepEqual(Object.keys(r).sort(),['ok','password_submitted']);});
test('a still-visible password form does not reject a delayed successful login',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:true,links:0},{ready:'complete',host:'power.houtai.backend.example.invalid',password:false,links:1},true,{host:'adopenplatform.backend.example.invalid',ready:'complete',password:false}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.ok,true);assert.equal(p.expressions.filter(x=>x.includes("document.querySelector('#submit').click()")).length,1);});
test('a pending request times out without being called a captcha',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:true,links:0}]);const r=await loginPortal(p,credentials,async()=>{});assert.equal(r.status,'LOGIN_PENDING_TIMEOUT');assert.equal(p.expressions.filter(x=>x.includes("document.querySelector('#submit').click()")).length,1);});
test('AI entry follows only the fixed AI portal link',async()=>{const p=page([{host:'power.houtai.backend.example.invalid',normal:true},true,{ready:'complete',host:'power.houtai.backend.example.invalid',password:false,links:1},true,{host:'ai.cn.sy.backend.example.invalid',ready:'complete',password:false}]);const r=await loginPortal(p,credentials,async()=>{},'ai.cn.sy.backend.example.invalid');assert.equal(r.ok,true);assert.ok(p.expressions[3].includes('ai.cn.sy.backend.example.invalid'));assert.ok(!JSON.stringify(r).includes('fixture-secret'));});
test('unknown entry cannot receive credentials',async()=>{const p=page([]);const r=await loginPortal(p,credentials,async()=>{},'example.com');assert.equal(r.status,'NONALLOWLISTED_ENTRY');assert.equal(p.expressions.length,0);});


// Execute the real DOM classifiers; do not pre-supply a synthetic challenge flag.
function portalDom({name='code',id='code',visibleBefore=true,visibleAfter=true}={}){
 let submits=0;const expressions=[];const form={};
 const field=(type,name,id)=>({type,name,id,form,value:'',getClientRects:()=>[{}],dispatchEvent:()=>{}});
 const username=field('text','username','username'),password=field('password','password','password');
 const code=field('text',name,id);
 code.getClientRects=()=>((submits?visibleAfter:visibleBefore)?[{}]:[]);
 const submit={click:()=>{submits++;}};
 const document={readyState:'complete',
  querySelector:selector=>({'#username':username,'#password':password,'#submit':submit,'input[type=password]':password}[selector]||null),
  querySelectorAll:selector=>selector==='input'?[username,password,code]:[]};
 return {expressions,get submits(){return submits;},send:async(method,args)=>{
  assert.equal(method,'Runtime.evaluate');expressions.push(args.expression);
  return {result:{value:vm.runInNewContext(args.expression,{document,location:{hostname:'power.houtai.backend.example.invalid'},Event:class {}})}};
 }};
}
test('visible code captcha is identified before credentials or submission checkpoint',async()=>{
 for(const descriptor of [{name:'code',id:''},{name:'',id:'code'},{name:'code',id:'code'}]){
  const p=portalDom(descriptor);let checkpoints=0;
  const r=await loginPortal(p,credentials,async()=>{},'ai.cn.sy.backend.example.invalid',async()=>{checkpoints++;});
  assert.equal(r.status,'LOGIN_OR_VERIFICATION_REQUIRED');assert.equal(p.submits,0);assert.equal(checkpoints,0);
  assert.equal(p.expressions.length,1);assert.ok(!p.expressions[0].includes('fixture-secret'));
 }
});
test('code captcha appearing after the one login send is not mislabeled pending timeout',async()=>{
 const p=portalDom({visibleBefore:false});let checkpoints=0;
 const r=await loginPortal(p,credentials,async()=>{},'ai.cn.sy.backend.example.invalid',async()=>{checkpoints++;});
 assert.equal(r.status,'LOGIN_OR_VERIFICATION_REQUIRED');assert.equal(r.password_submitted,true);
 assert.equal(p.submits,1);assert.equal(checkpoints,1);assert.equal(p.expressions.length,3);
 assert.ok(!JSON.stringify(r).includes('fixture-secret'));assert.equal(r.auto_retry,false);
});
test('hidden code fields and unrelated promotion codes do not manufacture a challenge',async()=>{
 for(const descriptor of [{visibleBefore:false,visibleAfter:false},{name:'promo_code',id:'promotion-code'}]){
  const p=portalDom(descriptor);const r=await loginPortal(p,credentials,async()=>{});
  assert.equal(r.status,'LOGIN_PENDING_TIMEOUT');assert.equal(p.submits,1);
 }
});
