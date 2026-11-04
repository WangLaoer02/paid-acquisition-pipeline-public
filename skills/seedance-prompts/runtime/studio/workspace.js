/* Human and Agent use one local store. The existing form/canvas stays in place. */
const humanActor={kind:'human',name:'本机用户'};
const shared={ready:false,applying:false,task:null,bundle:null,workspace:null,dirty:false,change:0,saving:null,timer:null,conflict:false,offline:false,panel:false,sequence:-1,panelTask:null,buffers:{},renderPending:false};
const statusNames={queued:'等待 Agent',running:'使用中',completed:'已提交结果',blocked:'待补条件',failed:'失败',cancelled:'已取消'};
const actorName=a=>a?`${a.kind==='agent'?'Agent':a.kind==='human'?'人':'系统'} · ${a.name}`:'等待领取';
const localTime=s=>s?new Date(s).toLocaleString('zh-CN',{hour12:false}):'';

async function api(path,method='GET',value){
  const res=await fetch(path,{method,cache:'no-store',headers:value?{'Content-Type':'application/json'}:{},body:value?JSON.stringify(value):undefined});
  const result=await res.json();
  if(!res.ok){const error=new Error(result.error||'工作台暂不可用');error.status=res.status;throw error}
  return result;
}
function sharedPayload(){
  return {form:form(),primary:state.primary,skills:route(),draft:state.draft,compiled:state.compiled,dirty:state.dirty,edited:state.edited,positions:state.positions,
    references:state.files.map((x,i)=>({...(x.asset||{}),label:refLabel(i),name:x.file.name,type:x.file.type,size:x.file.size,role:x.role,status:x.asset?'local_shared_not_platform_bound':'browser_only_not_shared'}))};
}
function syncLabel(text,problem=false){$('#workspace-sync').textContent=text;$('#workspace-sync').classList.toggle('sync-problem',problem)}
function sharedChanged(){
  if(!shared.ready||shared.applying)return;
  shared.dirty=true;shared.change++;syncLabel('有修改 · 正在保存');clearTimeout(shared.timer);
  if(!shared.conflict)shared.timer=setTimeout(()=>flushShared().catch(showSharedError),800);
}
function showSharedError(error){
  if(error.status===409){shared.conflict=true;$('#workspace-conflict').hidden=false;syncLabel('出现版本冲突 · 本地内容保留',true)}
  else{shared.offline=true;syncLabel('连接中断 · 修改尚未保存',true);toast(error.message)}
}
async function flushShared(kind='task_saved'){
  if(!shared.ready||shared.applying)return;
  clearTimeout(shared.timer);
  if(shared.conflict)throw Object.assign(new Error('先处理版本冲突；本地内容仍保留。'),{status:409});
  if(shared.saving){await shared.saving;if(shared.dirty)return flushShared(kind);return shared.task}
  if(!shared.dirty)return shared.task;
  const change=shared.change,payload=sharedPayload();
  shared.saving=(async()=>{
    const task=await api('/api/tasks/'+shared.task.id,'PATCH',{actor:humanActor,expected_revision:shared.task.revision,task:payload,event_type:kind});
    shared.task=task;shared.dirty=shared.change!==change;shared.offline=false;
    syncLabel(shared.dirty?'继续保存修改…':`本机已保存 · v${task.revision}`);return task;
  })();
  try{return await shared.saving}finally{shared.saving=null;if(shared.dirty&&!shared.conflict&&!shared.offline)shared.timer=setTimeout(()=>flushShared().catch(showSharedError),800)}
}
function applySharedTask(task){
  shared.applying=true;
  try{
    for(const f of state.files)if(f.url?.startsWith('blob:'))URL.revokeObjectURL(f.url);
    state.files=(task.references||[]).map(x=>({id:++fileCounter,file:{name:x.name,type:x.type,size:x.size},role:x.role,url:x.url||'',asset:x.id?x:null}));
    state.primary=task.primary;state.extras=task.skills.filter(s=>s!==ids.core&&s!==task.primary);state.selected=task.primary;state.positions=task.positions||{};
    selectSkill(task.primary);
    for(const [key,value] of Object.entries(task.form))if($('#'+key))$('#'+key).value=value;
    Object.assign(state,{draft:task.draft,compiled:task.compiled,dirty:task.dirty,edited:task.edited});
    shared.task=task;shared.dirty=false;shared.conflict=false;$('#workspace-conflict').hidden=true;
    $('#task-breadcrumb').textContent=task.form.title||'未命名任务';$('#preview-state').textContent=task.dirty?'输入已变更':task.compiled?'已保存 · 可编辑':'尚未整理';
    renderFiles();renderLibrary();renderAddons();renderPreview();renderNodes();renderInspector();if(state.view==='canvas')fit();
    $('#workspace-task-id').textContent=task.id;syncLabel(`本机已保存 · v${task.revision}`);
  }finally{shared.applying=false}
}
async function pollShared(force=false){
  if(!shared.ready)return;
  const data=await api('/api/state');if(data.sequence<shared.sequence)return;shared.workspace=data;shared.offline=false;
  let current=data.current;
  if(current&&shared.task&&current.task.id!==shared.task.id){
    // The shared active pointer can change in another chat; keep unsaved edits on this page.
    if(shared.dirty||shared.saving||shared.conflict){syncLabel('其他会话已切换任务 · 本页修改保留',true);current=await api('/api/tasks/'+shared.task.id)}
    else applySharedTask(current.task);
  }
  if(current?.task.id===shared.task?.id){
    if(current.task.revision>shared.task.revision&&!shared.dirty&&!shared.saving&&!shared.conflict)applySharedTask(current.task);
    if(current.task.revision>=shared.task.revision)shared.bundle=current;
  }
  const changed=data.sequence!==shared.sequence;shared.sequence=data.sequence;
  $('#history-count').textContent=shared.bundle?.events.length||0;
  if(changed||force){renderUsageNodes();renderState();shared.renderPending=true}
  if(shared.panel&&shared.renderPending&&!document.activeElement?.matches('#workspace-panel textarea,#workspace-panel input,#workspace-panel select'))renderWorkspacePanel();
}
function renderUsageNodes(){
  for(const node of $$('[data-node]')){
    const runs=(shared.bundle?.runs||[]).filter(r=>r.skills.some(s=>s.slug===node.dataset.node));const last=runs.at(-1);
    if(last){const label=node.querySelector('.node-foot span');if(label)label.textContent=`${last.actor?.kind==='agent'?'Agent':last.actor?.kind==='human'?'人工':'Agent'} · ${statusNames[last.status]}`}
  }
}
function renderWorkspacePanel(){
  const data=shared.workspace,b=shared.bundle;if(!data||!b)return;
  const selectedTask=shared.task.id;
  if(shared.panelTask===selectedTask){for(const input of $$('#workspace-panel textarea[id]'))shared.buffers[input.id]=input.value}else shared.buffers={};
  shared.panelTask=selectedTask;shared.renderPending=false;
  $('#workspace-panel-body').innerHTML=`
    <div class="workspace-task-row"><select class="field small" id="history-task" aria-label="选择历史任务">${data.tasks.map(t=>`<option value="${t.id}" ${t.id===selectedTask?'selected':''}>${esc(t.title)} · v${t.revision}</option>`).join('')}</select><button class="small-button" id="new-shared-task">新任务</button></div>
    <p class="workspace-help">${esc(selectedTask)}<br>任务、素材副本与使用流水保存在本机，人与 Agent 共用。</p>
    <div class="workspace-actions"><button class="small-button agent-copy" id="queue-agent">交给 Agent</button><button class="small-button" id="start-human">开始人工使用</button><button class="small-button" id="copy-agent-entry">复制 Agent 接续指令</button></div>
    <p class="workspace-help">“交给 Agent”登记待办。把接续指令发给当前 Agent 即可领取；当前没有常驻自动执行器。只按任务停止点执行，生成与费用授权另行核对。</p>
    <div class="workspace-section">Skill 使用记录 · ${b.runs.length}</div>
    <div id="usage-runs">${b.runs.length?[...b.runs].reverse().map(runCard).join(''):'<div class="workspace-empty">尚无 Skill 执行记录。选择方法与整理草稿会分别留痕。</div>'}</div>
    <details style="margin-top:18px"><summary class="workspace-help">已保存版本 · ${b.versions?.length||0}（最近 100 版）</summary><div class="workspace-task-row"><select class="field small" id="saved-version" aria-label="选择任务保存版本">${(b.versions||[]).map(v=>`<option value="${v.revision}">v${v.revision} · ${esc(localTime(v.updated_at))}</option>`).join('')}</select><button class="small-button" id="view-saved-version">查看草稿</button></div><pre class="usage-output" id="saved-version-preview" hidden></pre><button class="small-button" id="restore-version-draft" hidden>恢复此版草稿</button></details>
    <div class="workspace-section">补充说明</div><div class="workspace-note-row"><textarea class="field" id="record-note" aria-label="使用记录说明" rows="2" placeholder="记录真实进度、反馈或待补条件"></textarea><button class="small-button" id="save-record-note">保存说明</button></div>
    <div class="workspace-section">操作流水 · 最近 200 条</div><div>${b.events.map(e=>`<div class="event-row"><small>${esc(localTime(e.at))}　${esc(actorName(e.actor))}</small><p>${esc(e.summary)}</p>${e.run_id?`<small>${esc(e.run_id)}</small>`:''}</div>`).join('')}</div>`;
  $('#history-task').onchange=async e=>runUI(async()=>{await flushShared();await api('/api/tasks/'+e.target.value+'/activate','POST',{actor:humanActor});await pollShared(true);renderWorkspacePanel()});
  $('#new-shared-task').onclick=()=>runUI(newSharedTask);
  $('#queue-agent').onclick=()=>runUI(async()=>{await flushShared();const r=await api('/api/tasks/'+shared.task.id+'/runs','POST',{actor:humanActor,queued:true,skills:route(),request_key:crypto.randomUUID(),summary:'按当前任务停止点处理；保留原稿与人工草稿'});await pollShared(true);renderWorkspacePanel();toast('已登记待办；复制接续指令交给当前 Agent。')});
  $('#start-human').onclick=()=>runUI(async()=>{await flushShared();await api('/api/tasks/'+shared.task.id+'/runs','POST',{actor:humanActor,skills:route(),summary:'人工开始使用所选 Skill'});await pollShared(true);renderWorkspacePanel()});
  $('#copy-agent-entry').onclick=()=>copyAgentEntry();
  let viewedVersion=null;
  $('#view-saved-version').onclick=()=>runUI(async()=>{viewedVersion=await api('/api/tasks/'+shared.task.id+'/versions/'+$('#saved-version').value);$('#saved-version-preview').hidden=false;$('#saved-version-preview').textContent=viewedVersion.draft||'此版没有草稿';$('#restore-version-draft').hidden=!viewedVersion.draft});
  $('#restore-version-draft').onclick=()=>runUI(async()=>{if(!viewedVersion)return;if(state.draft&&state.draft!==viewedVersion.draft&&!confirm('恢复会替换当前草稿，当前保存版仍可回看。继续吗？'))return;state.draft=viewedVersion.draft;state.compiled=true;state.edited=true;state.dirty=false;renderPreview();sharedChanged();await flushShared();await pollShared(true);renderWorkspacePanel()});
  $('#save-record-note').onclick=()=>runUI(async()=>{const text=$('#record-note').value.trim();if(!text)return;await api('/api/tasks/'+shared.task.id+'/notes','POST',{actor:humanActor,summary:text});$('#record-note').value='';shared.buffers['record-note']='';await pollShared(true);renderWorkspacePanel()});
  $$('[data-adopt-run]').forEach(el=>el.onclick=()=>runUI(()=>adoptRun(el.dataset.adoptRun)));
  $$('[data-finish-human]').forEach(el=>el.onclick=()=>runUI(async()=>{const id=el.dataset.finishHuman;const output=$('#human-output-'+id).value.trim();if(!output){toast('填写实际使用结果后再记录完成。');return}await api('/api/runs/'+id+'/finish','POST',{actor:humanActor,status:'completed',summary:'人工提交使用结果',output});await pollShared(true);renderWorkspacePanel()}));
  $$('[data-cancel-run]').forEach(el=>el.onclick=()=>runUI(async()=>{await api('/api/runs/'+el.dataset.cancelRun+'/finish','POST',{actor:humanActor,status:'cancelled',summary:'用户取消本次使用'});await pollShared(true);renderWorkspacePanel()}));
  for(const [id,value] of Object.entries(shared.buffers)){const input=$('#'+id);if(input)input.value=value}
}
function runCard(r){
  const names=r.skills.map(s=>skill(s.slug)?.title||s.slug).join('、');
  return `<article class="usage-card"><div class="usage-header"><strong>${esc(actorName(r.actor||r.requested_by))}</strong><span class="usage-status ${r.status}">${esc(statusNames[r.status])}</span></div><p>${esc(r.summary)}</p><div class="usage-meta">${esc(names)}<br>${esc(r.id)} · 输入 v${r.input_revision}<br>${esc(localTime(r.started_at||r.created_at))}</div>
    ${r.output?`<details><summary>查看候选结果</summary><pre class="usage-output">${esc(r.output)}</pre><button class="small-button" data-adopt-run="${r.id}">采用到当前草稿</button></details>`:''}
    ${r.evidence?.length?`<div class="usage-meta">证据：${r.evidence.map(x=>esc(typeof x==='string'?x:JSON.stringify(x))).join('<br>')}</div>`:''}
    <details><summary>输入快照与 Skill 指纹</summary><pre class="usage-output">${esc(JSON.stringify({input:r.input_snapshot.form,references:r.input_snapshot.references,skills:r.skills},null,2))}</pre></details>
    ${r.status==='running'&&r.actor?.kind==='human'?`<label class="workspace-input-label" for="human-output-${r.id}">实际使用结果</label><textarea class="field" id="human-output-${r.id}" rows="3" placeholder="填写实际完成的文字或产物说明"></textarea><button class="small-button" data-finish-human="${r.id}">记录完成</button>`:''}
    ${['queued','running'].includes(r.status)?`<button class="small-button" data-cancel-run="${r.id}">取消本次使用</button>`:''}</article>`;
}
async function runUI(action){try{await action()}catch(error){showSharedError(error);toast(error.message)}}
async function openWorkspace(){
  if(!shared.ready){toast('共用服务尚未连接，请通过本机服务打开。');return}
  await runUI(async()=>{await flushShared();await pollShared(true);shared.panel=true;$('#workspace-panel').hidden=false;renderWorkspacePanel();$('#close-workspace').focus()});
}
async function newSharedTask(){
  await flushShared();const current=sharedPayload();
  const task=await api('/api/tasks','POST',{actor:humanActor,task:{...current,form:{...current.form,title:'新的 Seedance 任务',source:''},draft:'',compiled:false,dirty:false,edited:false,references:[],positions:{}}});
  applySharedTask(task);await pollShared(true);renderWorkspacePanel();toast('已创建新任务，原任务保留。');
}
async function adoptRun(id){
  const run=shared.bundle.runs.find(r=>r.id===id);if(!run?.output)return;
  if(state.draft.trim()&&state.draft!==run.output&&!confirm('采用会替换当前草稿。现有草稿仍在任务保存记录中，继续吗？'))return;
  state.draft=run.output;state.compiled=true;state.edited=true;state.dirty=false;state.tab='draft';renderPreview();sharedChanged();
  await flushShared('candidate_adopted');await pollShared(true);toast('已采用候选结果，使用记录保留。');
}
async function copyAgentEntry(){
  await runUI(async()=>{await flushShared();const q=[...(shared.bundle?.runs||[])].reverse().find(r=>r.status==='queued');
    await copy(`请在本机 Seedance 工作台处理任务 ${shared.task.id}。先读取 skills/seedance-prompts/runtime/studio/AGENT.md 。\n${q?'领取使用记录 '+q.id+'，':''}读取任务原稿、选中 Skill 正文与当前输入版本，只到指定停止点；记录进度并提交候选结果，保留人工草稿。当前没有付费生成授权。`,'已复制 Agent 接续指令。')});
}

// Attach persistence to existing interactions, without replacing their entry points.
const oldMarkDirty=markDirty;markDirty=function(){oldMarkDirty();sharedChanged()};
const oldPreview=renderPreview;renderPreview=function(){oldPreview();const editor=$('#output-editor');if(editor){const input=editor.oninput;editor.oninput=e=>{input?.(e);sharedChanged()}}};
const oldNodes=renderNodes;renderNodes=function(){oldNodes();renderUsageNodes()};
const oldCompose=compose;compose=function(){const before=JSON.stringify([state.draft,state.compiled,state.dirty,state.edited]);oldCompose();if(state.compiled&&before!==JSON.stringify([state.draft,state.compiled,state.dirty,state.edited])){sharedChanged();flushShared('draft_prepared').catch(showSharedError)}};
$('#compose-button').onclick=compose;
const oldFiles=renderFiles;renderFiles=function(){oldFiles();$$('.file-row').forEach((row,i)=>{const status=row.querySelector('.file-status');if(status)status.textContent=state.files[i].asset?'本机共享 · 未绑定':'待保存到本机'})};
const oldAddFiles=addFiles;addFiles=async function(files){
  if(!shared.ready){oldAddFiles(files);return}
  const oldIds=new Set(state.files.map(x=>x.id));oldAddFiles(files);
  for(const f of state.files.filter(x=>!oldIds.has(x.id))){
    try{const res=await fetch('/api/tasks/'+shared.task.id+'/assets?name='+encodeURIComponent(f.file.name),{method:'POST',headers:{'Content-Type':f.file.type},body:f.file});const asset=await res.json();if(!res.ok)throw new Error(asset.error);f.asset=asset;renderFiles();sharedChanged()}
    catch(error){toast('素材未共享：'+error.message)}
  }
};
const oldNodeDown=nodeDown;nodeDown=function(e,id){oldNodeDown(e,id);const node=$(`[data-node="${id}"]`),up=node?.onpointerup;if(up)node.onpointerup=()=>{up();sharedChanged()}};
const oldPacket=packet;packet=function(){return {...oldPacket(),execution:'see_usage_records',mode:'shared_human_agent_workspace',checks:{workbench_invoked_model:false,platform_binding_verified:false,generation_submitted:false,use_records_for_agent_status:true},workspace:{task_id:shared.task?.id,revision:shared.task?.revision,runs:shared.bundle?.runs||[],events:shared.bundle?.events||[]},references:sharedPayload().references}};
const oldHandoff=handoffText;handoffText=function(){return shared.ready?`共用任务：${shared.task.id}\n先读取本机工作台 AGENT.md 并按 task_id 接续；用 CLI 记录真实使用与结果。\n\n`+oldHandoff():oldHandoff()};

document.querySelector('.top-actions').insertAdjacentHTML('afterbegin','<button class="small-button" id="workspace-history">任务与记录 <span class="record-count" id="history-count">0</span></button>');
document.querySelector('.subbar').insertAdjacentHTML('afterend',`<div class="workspace-strip"><strong>人 + Agent 共用</strong><span id="workspace-sync" role="status">正在连接本机记录…</span><span id="workspace-task-id"></span><button class="workspace-link" id="save-shared">保存</button></div><div class="workspace-conflict" id="workspace-conflict" hidden>共用任务出现新版本。本地输入仍保留；请先另存本地内容，再查看共用版本。<br><button class="small-button" id="fork-local">另存本地为新任务</button><button class="small-button" id="load-remote">载入共用版本</button></div>`);
document.body.insertAdjacentHTML('beforeend','<section class="workspace-panel" id="workspace-panel" hidden role="dialog" aria-modal="true" aria-labelledby="workspace-panel-title"><div class="workspace-sheet"><div class="workspace-head"><div><h2 id="workspace-panel-title">任务与使用记录</h2><p>同一份任务，人与 Agent 都能接续</p></div><button class="small-button" id="close-workspace" aria-label="关闭任务与记录">关闭</button></div><div class="workspace-body" id="workspace-panel-body"></div></div></section>');
$('#workspace-history').onclick=openWorkspace;$('#close-workspace').onclick=()=>{shared.panel=false;$('#workspace-panel').hidden=true;$('#workspace-history').focus()};
$('#workspace-panel').onclick=e=>{if(e.target===$('#workspace-panel'))$('#close-workspace').click()};
$('#save-shared').onclick=()=>runUI(async()=>{await flushShared();syncLabel(`本机已保存 · v${shared.task.revision}`)});
$('#fork-local').onclick=()=>runUI(async()=>{const task=await api('/api/tasks','POST',{actor:humanActor,task:sharedPayload()});applySharedTask(task);await pollShared(true)});
$('#load-remote').onclick=()=>runUI(async()=>{if(!confirm('载入会替换本页未保存的内容；可以先另存为新任务。继续吗？'))return;const b=await api('/api/tasks/'+shared.task.id);applySharedTask(b.task);await pollShared(true)});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&shared.panel)$('#close-workspace').click()});
window.addEventListener('beforeunload',e=>{if(shared.dirty||shared.saving){e.preventDefault();e.returnValue=''}});

async function initWorkspace(){
  if(location.protocol==='file:'){syncLabel('离线快照 · 无共用记录',true);return}
  try{
    let data=await api('/api/state');
    if(!data.current){await api('/api/tasks','POST',{actor:humanActor,task:sharedPayload()});data=await api('/api/state')}
    shared.workspace=data;shared.bundle=data.current;applySharedTask(data.current.task);shared.ready=true;shared.sequence=data.sequence;
    $('#history-count').textContent=shared.bundle.events.length;renderUsageNodes();
    setInterval(()=>pollShared().catch(()=>{shared.offline=true;syncLabel('共用服务暂不可用 · 本地输入保留',true)}),1800);
  }catch(error){syncLabel('共用服务未连接 · 可继续编辑与导出',true)}
}
initWorkspace();
