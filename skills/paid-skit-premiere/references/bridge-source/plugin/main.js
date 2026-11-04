const ppro = require('premierepro');
const uxp = require('uxp');
const VERSION = '0.2.1';
const SESSION = Date.now()+'-'+Math.random().toString(36).slice(2);
let enabled = false, busy = false, timer = null;
function show(message, detail='') {
  const status=document.getElementById('status'), info=document.getElementById('detail');
  if(status) status.textContent=message;
  if(info && detail) info.textContent=detail;
}
function pathEqual(a,b) { return String(a).normalize('NFC')===String(b).normalize('NFC'); }
function guid(value) { return value == null ? null : String(value); }
function time(value) { return value == null ? null : {seconds:value.seconds, ticks:String(value.ticks)}; }
const localFS=uxp.storage.localFileSystem;
let sandbox=null;
async function storage() {
  if(sandbox)return sandbox;
  const data=await localFS.getDataFolder();
  sandbox={data,plugin:await localFS.getPluginFolder()};
  return sandbox;
}
async function heartbeat() {
  const {data,plugin}=await storage();
  const challenge=JSON.parse(await (await plugin.getEntry('bridge-health-request.json')).read());
  if(challenge.version!==VERSION || !challenge.controller_id || !pathEqual(challenge.mailbox_path,plugin.nativePath.replace(/\/$/,'')+'/bridge-job.json'))throw Error('HEALTH_CONTROLLER_MISMATCH');
  await (await data.createFile('bridge-ready.json',{overwrite:true})).write(JSON.stringify({
    version:VERSION,session_id:SESSION,controller_id:challenge.controller_id,mailbox_path:challenge.mailbox_path,
    heartbeat_at_ms:Date.now(),enabled,busy,data_path:data.nativePath,transport:'plugin-sandbox-files'
  }));
}
async function request(url,payload) {
  const {data,plugin}=await storage();
  if(url==='/next') {
    let job;
    try {job=JSON.parse(await (await plugin.getEntry('bridge-job.json')).read());}catch(e){return {job:null};}
    if(!job || !job.id)return {job:null};
    let claims=[];
    // Only a genuinely absent file means no claims. Corruption/read failures
    // must never replay a previously accepted native operation.
    const entries=await data.getEntries();
    if(entries.some(entry=>entry.name==='claimed-jobs.json'))claims=JSON.parse(await (await data.getEntry('claimed-jobs.json')).read());
    if(!Array.isArray(claims) || !claims.every(id=>typeof id==='string'))throw Error('INVALID_CLAIM_STORAGE');
    if(claims.includes(job.id))return {job:null};
    claims.push(job.id);
    await (await data.createFile('claimed-jobs.json',{overwrite:true})).write(JSON.stringify(claims));
    return {job};
  }
  if(url.startsWith('/result/')) {
    const id=url.slice(8), name='receipt-'+id+'.json';
    let receipt={id,events:[]};
    try {receipt=JSON.parse(await (await data.getEntry(name)).read());}catch(e){}
    receipt.status=payload.status;receipt.events.push({at:new Date().toISOString(),...payload});
    if(payload.result)receipt.result=payload.result;
    if(payload.error)receipt.error=payload.error;
    await (await data.createFile(name,{overwrite:true})).write(JSON.stringify(receipt));
    return {ok:true};
  }
  throw new Error('TRANSPORT_ACTION_NOT_ALLOWED');
}
async function guard(job,phase) {
  const nonce=job.id+'-'+phase+'-'+Date.now();
  await request('/result/'+job.id,{status:'preflight',phase,nonce});
  const {plugin}=await storage();
  const deadline=Date.now()+10000;
  while(Date.now()<deadline) {
    let permit=null;
    try {permit=JSON.parse(await (await plugin.getEntry('permit-'+job.id+'-'+phase+'.json')).read());}catch(e){}
    if(permit && permit.id===job.id && permit.phase===phase && permit.nonce===nonce) {
      if(!permit.ok)throw new Error(permit.error||'GUARD_REFUSED');
      if(Date.now()>=permit.expires_at_ms)throw new Error('GUARD_EXPIRED');
      return;
    }
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('GUARD_TIMEOUT_QUERY_ORIGINAL_JOB');
}
async function inspect(project) {
  if(!project)throw new Error('NO_ACTIVE_PROJECT');
  const sequence=await project.getActiveSequence();
  const sequences=await project.getSequences();
  const rect=sequence?await sequence.getFrameSize():null;
  const result={bridge_version:VERSION,host_name:uxp.host?.name,host_version:uxp.host?.version,
    project_path:project.path,project_guid:guid(project.guid),sequence_count:sequences.length,
    direct_export_api:typeof ppro.EncoderManager?.getManager==='function'};
  if(sequence) {
    result.sequence={name:sequence.name,guid:guid(sequence.guid),in_point:time(await sequence.getInPoint()),
      out_point:time(await sequence.getOutPoint()),end:time(await sequence.getEndTime()),
      timebase:await sequence.getTimebase(),frame_size:rect?{width:rect.width,height:rect.height}:null,
      audio_track_count:await sequence.getAudioTrackCount(),caption_track_count:await sequence.getCaptionTrackCount(),audio_tracks:[],caption_tracks:[]};
    for(let i=0;i<result.sequence.audio_track_count;i++) {
      const track=await sequence.getAudioTrack(i);
      result.sequence.audio_tracks.push({index:i,name:track.name,muted:await track.isMuted()});
    }
    for(let i=0;i<result.sequence.caption_track_count;i++) {
      const track=await sequence.getCaptionTrack(i);
      result.sequence.caption_tracks.push({index:i,name:track.name,muted:await track.isMuted()});
    }
  }
  return result;
}
async function execute(job) {
  // A stranded 0.2.0 read-only request can finish under the same ID/mailbox.
  // Legacy writes cannot acquire this compatibility exception.
  if(job.protocol!==2 || (job.bridge_version!==VERSION && !(job.action==='inspect' && job.bridge_version==='0.2.0')))throw new Error('BRIDGE_PROTOCOL_MISMATCH');
  let project=await ppro.Project.getActiveProject();
  if(job.action==='inspect')return await inspect(project);
  if(job.action==='snapshot-copy') {
    if(!project || !pathEqual(project.path,job.original_path))throw new Error('ORIGINAL_PROJECT_IDENTITY_MISMATCH');
    const before=await inspect(project);
    await guard(job,'save');
    job.native_side_effect_possible=true;
    const saved=await project.saveAs(job.copy_path);
    project=await ppro.Project.getActiveProject();
    if(!saved || !pathEqual(project.path,job.copy_path))throw new Error('COPY_SAVE_NOT_VERIFIED');
    return {before,after:await inspect(project),save_result:saved,original_project_saved:false};
  }
  if(job.action==='open-copy' || job.action==='restore-original') {
    const target=job.action==='open-copy'?job.copy_path:job.original_path;
    const options=new ppro.OpenProjectOptions();
    options.setShowConvertProjectDialog(false).setShowLocateFileDialog(false).setShowWarningDialog(true);
    if(job.action==='open-copy')await guard(job,'save');
    job.native_side_effect_possible=true;
    project=await ppro.Project.open(target,options);
    if(!pathEqual(project.path,target))throw new Error('OPEN_IDENTITY_MISMATCH');
    return await inspect(project);
  }
  if(job.action==='export-a') {
    if(!project || !pathEqual(project.path,job.copy_path) || !job.project_guid || guid(project.guid)!==job.project_guid)throw new Error('EXPORT_REQUIRES_TEST_COPY');
    const sequence=await project.getActiveSequence();
    if(typeof job.sequence_guid!=='string' || !job.sequence_guid.trim() || !sequence || guid(sequence.guid)!==job.sequence_guid)throw new Error('SEQUENCE_IDENTITY_MISMATCH');
    const snapshot=await inspect(project);
    if(Math.abs(snapshot.sequence.in_point.seconds-job.in_seconds)>0.000001 || Math.abs(snapshot.sequence.out_point.seconds-job.out_seconds)>0.000001)throw new Error('EXPORT_RANGE_MISMATCH');
    if(!job.preset_path || job.use_applied_settings)throw new Error('EXPLICIT_VALIDATED_EPR_REQUIRED');
    await guard(job,'save');
    job.native_side_effect_possible=true;
    if(!await project.saveAs(job.save_path))throw new Error('COPY_SAVE_FAILED');
    project=await ppro.Project.getActiveProject();
    if(!pathEqual(project.path,job.save_path))throw new Error('SAVE_IDENTITY_MISMATCH');
    const savedSequence=await project.getActiveSequence();
    if(!savedSequence || guid(savedSequence.guid)!==job.sequence_guid)throw new Error('SAVED_SEQUENCE_IDENTITY_MISMATCH');
    await guard(job,'export');
    await request('/result/'+job.id,{status:'exporting',snapshot,export_backend:'Premiere UXP IMMEDIATELY',output_path:job.output_path,preset_path:job.preset_path||null});
    if(!job.preset_path || job.use_applied_settings)throw new Error('EXPLICIT_VALIDATED_EPR_REQUIRED');
    const manager=ppro.EncoderManager.getManager();
    const result=await manager.exportSequence(savedSequence,ppro.Constants.ExportType.IMMEDIATELY,job.output_path,job.preset_path,false);
    return {native_call_returned:result,export_backend:'Premiere UXP IMMEDIATELY',snapshot,
      output_path:job.output_path,saved_copy_path:job.save_path,preset_path:job.preset_path||null,export_full:false,
      completion_requires_output_verification:true};
  }
  throw new Error('ACTION_NOT_ALLOWED');
}
async function poll() {
  if(!enabled || busy)return;
  busy=true;
  let job;
  try {
    await heartbeat();
    const response=await request('/next');job=response.job;
    if(!job) {show('Connected via plugin sandbox files.');return;}
    show('Running '+job.action,job.id);
    await request('/result/'+job.id,{status:'accepted',action:job.action,bridge_version:VERSION});
    const result=await execute(job);
    await request('/result/'+job.id,{status:'native_call_returned',result});
    show('Returned; verify '+job.action,job.id);
  } catch(error) {
    const message=String(error?.message||error);
    show('Bridge: '+message);
    if(job)try {await request('/result/'+job.id,{status:job.native_side_effect_possible?'unknown':'failed',error:message,stack:String(error?.stack||'')});}catch(ignored){}
  } finally {busy=false;try {await heartbeat();}catch(ignored){}}
}
function start() {if(enabled)return;enabled=true;timer=setInterval(poll,1500);poll();}
function stop() {enabled=false;if(timer)clearInterval(timer);timer=null;show('Disconnected.');return heartbeat().catch(()=>{});}
uxp.entrypoints.setup({panels:{paidSkitBridge:{show(){
  document.getElementById('start').onclick=start;
  document.getElementById('stop').onclick=stop;
  start();
},hide(){},destroy(){stop();}}}});
