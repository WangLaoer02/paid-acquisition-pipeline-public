import test from 'node:test';
import assert from 'node:assert/strict';
import {navigate,LIST,validateListRows} from './upload_bridge.mjs';
const blocked={send:async()=>({errorText:'net::ERR_BLOCKED_BY_CLIENT'})};
function histogram(counts){let n=0;return {send:async(method)=>{assert.equal(method,'Browser.getHistograms');return {histograms:[{name:'Security.HttpsFirstMode.InterstitialReason',count:counts[n++]}]};}};}
test('a new Chrome HTTP interstitial is distinguished from an extension block',async()=>{
 const r=await navigate(blocked,LIST,histogram([3,4]));
 assert.equal(r.status,'BROWSER_HTTP_CONFIRMATION_REQUIRED');assert.equal(r.native_user_action_required,true);
 assert.equal(r.upload_performed,false);assert.deepEqual(r.evidence.before,3);assert.equal(r.evidence.after,4);
});
test('historical interstitials do not misclassify a new unrelated block',async()=>{
 const r=await navigate(blocked,LIST,histogram([4,4]));assert.equal(r.status,'UPLOAD_CLIENT_BLOCKED');
});
test('missing browser metrics keep the cause unknown',async()=>{
 const r=await navigate(blocked,LIST,{send:async()=>{throw Error('unavailable')}});assert.equal(r.status,'UPLOAD_CLIENT_BLOCKED');
});
test('unexpected domains fail before navigation or metrics',async()=>{
 await assert.rejects(navigate({send:()=>{throw Error('should not run')}},'http://example.com/'),/NONALLOWLISTED_ENTRY/);
});
test('a positive backend count cannot silently become an empty list',()=>{
 assert.equal(validateListRows([],2),null);
 assert.deepEqual(validateListRows([],0),[]);
});
test('a partial first page is valid and an unknown total is not',()=>{
 const records=[{record_id:'123',name:'261011视频'}];
 assert.deepEqual(validateListRows(records,75),records);
 assert.equal(validateListRows(records,null),null);
 assert.equal(validateListRows(records,0),null);
});
test('unpaired or malformed cards fail instead of bypassing duplicate checks',()=>{
 assert.equal(validateListRows([{record_id:'123',name:null}],1),null);
 assert.equal(validateListRows([{record_id:'bad',name:'视频'}],1),null);
});
test('duplicate record ids fail even when the count matches',()=>{
 assert.equal(validateListRows([{record_id:'123',name:'A'},{record_id:'123',name:'B'}],2),null);
});
test('login form is not actionable until its page scripts finish loading',async()=>{
 let reads=0;
 const page={send:async(method)=>method==='Page.navigate'?{}:{result:{value:{host:'power.houtai.backend.example.invalid',ready:++reads===1?'loading':'complete',password:true,body:true}}}};
 const r=await navigate(page,LIST);assert.equal(r.status,'UPLOAD_LOGIN_REQUIRED');assert.equal(reads,2);
});
