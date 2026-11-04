const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const who={kind:'human',name:'本机用户'};
const state={data:null,runId:new URLSearchParams(location.search).get('run'),stepId:new URLSearchParams(location.search).get('step'),mode:'runs',selectedIssue:new URLSearchParams(location.search).get('issue'),signature:'',request:0,applied:0,compareIssue:null,editIssue:null};
const statuses={queued:'等待',running:'运行中',completed:'完成',failed:'失败',blocked:'等待',cancelled:'已取消'};
const issueStatuses={open:'新发现',working:'处理中',resolved:'已解决'};
const fieldNames={title:'任务',source:'用户原稿与目标',style:'画风与场景',keep:'必须保留',duration:'目标总时长',aspect:'画幅',format:'输出格式',stop:'本次做到哪一步',project:'项目',command:'命令',cwd:'工作目录'};
const values={video:'视频',prompt:'提示词',storyboard:'故事板',handoff:'制作交接',natural:'自然语言',five:'五段式',timeline:'时间线'};
const kindNames={tool:'工具执行',input:'输入准备',check:'结果检查',artifact:'产物记录',skill:'Skill 调用',reference:'参考读取',skill_read:'Skill 调用',reference_read:'参考读取',context_read:'上下文读取',progress:'进度记录'};
let toastTimer;
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,2800)}
async function api(path,method='GET',value){const res=await fetch(path,{method,cache:'no-store',headers:value?{'Content-Type':'application/json'}:{},body:value?JSON.stringify(value):undefined});const data=await res.json();if(!res.ok)throw new Error(data.error||'操作失败');return data}
function clock(at){return at?new Date(at).toLocaleTimeString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):''}
function date(at){return at?new Date(at).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):''}
function actor(a){return a?(a.kind==='agent'?'Agent · ':a.kind==='human'?'人工 · ':'系统 · ')+a.name:'等待执行'}
function duration(ms){if(ms==null)return '';return ms<1000?ms+' ms':ms<60000?(ms/1000).toFixed(1)+' 秒':Math.floor(ms/60000)+' 分 '+Math.round(ms%60000/1000)+' 秒'}
function run(){return state.data?.runs.find(r=>r.id===state.runId)}
function step(){return run()?.steps.find(s=>s.id===state.stepId)}
function issue(id){return state.data?.issues.find(i=>i.id===id)}
function compact(text,length=105){const s=String(text||'').replace(/\bUID\s*\d+/g,'').replace(/\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi,'').replace(/\s+/g,' ').trim();return s.length>length?s.slice(0,length)+'…':s}
function resultText(r){
  if(r.output)return r.output;
  if(['running','queued'].includes(r.status)){
    const recent=[...r.steps].reverse().find(s=>!['run_started','run_queued','context_read'].includes(s.kind)&&(s.status==='running'||s.error||s.summary||s.output));
    if(recent?.status==='running')return recent.title+'：执行中';
    if(recent){const detail=recent.error||recent.reason||recent.summary||(typeof recent.output==='string'?recent.output:JSON.stringify(recent.output));return detail===recent.title?recent.title:recent.title+'：'+detail}
  }
  return r.summary||'还没有提交结果';
}
function category(i){return state.data?.categories?.[i.category]||'输出结果'}
function matchingIssues(r){const selected=$('#category-filter').value,status=$('#issue-status-filter').value;return r.issues.filter(i=>(!selected||i.category===selected)&&(!status||i.status===status))}
function visibleRuns(){
  if(!state.data)return [];
  const keyword=$('#search').value.trim().toLowerCase(),skill=$('#skill-filter').value,time=$('#time-filter').value;
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
  return state.data.runs.filter(r=>{
    if(!$('#show-tests').checked&&r.is_test)return false;
    if($('#only-issues').checked&&!r.issue_count)return false;
    if(($('#category-filter').value||$('#issue-status-filter').value)&&!matchingIssues(r).length)return false;
    if(skill&&!r.skills.some(s=>s.slug===skill))return false;
    if(time==='today'&&new Date(r.started_at||r.created_at).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'})!==today)return false;
    if(time==='week'&&Date.now()-new Date(r.started_at||r.created_at).getTime()>7*86400000)return false;
    return !keyword||JSON.stringify([r.title,r.input_snapshot.form,r.summary,r.output,r.skill_titles,r.skills,r.steps,r.issues]).toLowerCase().includes(keyword);
  });
}
function revealWithin(container,element){if(!element)return;const c=container.getBoundingClientRect(),e=element.getBoundingClientRect();if(e.top<c.top)container.scrollTop-=c.top-e.top;else if(e.bottom>c.bottom)container.scrollTop+=e.bottom-c.bottom;if(e.left<c.left)container.scrollLeft-=c.left-e.left;else if(e.right>c.right)container.scrollLeft+=e.right-c.right}
function selectRun(id,stepId=null,issueId=null){
  state.runId=id;const r=run();if(!r)return;
  state.stepId=r.steps.some(s=>s.id===stepId)?stepId:null;state.selectedIssue=r.issues.some(i=>i.id===issueId)?issueId:null;
  const url=new URL(location.href);url.searchParams.set('run',id);if(state.stepId)url.searchParams.set('step',state.stepId);else url.searchParams.delete('step');if(state.selectedIssue)url.searchParams.set('issue',state.selectedIssue);else url.searchParams.delete('issue');history.replaceState(null,'',url);
  renderList();renderRun();renderDetail();
  revealWithin($('#run-list'),$('#run-list .active'));revealWithin($('#timeline'),$('#timeline .active'));$('#step-detail').scrollTop=0;
}
function emptyMessage(){const skill=state.data?.skills.find(s=>s.slug===$('#skill-filter').value);return `<strong>没有符合筛选的运行</strong>${skill?esc(skill.title)+' · '+esc(skill.slug)+'<br>该 Skill 的记录也从统一入口接入。':'调整 Skill、时间或关键词'}`}
function renderList(){
  const rows=visibleRuns();const issues=rows.flatMap(r=>matchingIssues(r).map(i=>({...i,run:r}))).sort((a,b)=>(a.status==='resolved')-(b.status==='resolved')||new Date(b.updated_at||b.created_at)-new Date(a.updated_at||a.created_at));
  $('#run-count').textContent=state.mode==='runs'?rows.length:issues.length;
  $('#list-heading').textContent=state.mode==='runs'?'全部运行':'全部问题';
  $('#list-count').textContent=rows.length+' 次运行 · '+issues.length+' 条问题记录';
  if(state.mode==='runs'){
    $('#run-list').innerHTML=rows.map(r=>{
      const activeIssues=matchingIssues(r).filter(i=>i.status!=='resolved');
      return `<button class="run-card ${r.id===state.runId?'active':''}" data-run="${r.id}" aria-pressed="${r.id===state.runId}"><div class="run-topline"><span class="run-meta">${esc(date(r.started_at||r.created_at))}${r.is_test?'<span class="test-label">测试</span>':''}</span><span class="status ${r.status}">${statuses[r.status]||r.status}</span></div><div class="run-title">${esc(r.title)}</div><div class="run-meta">${esc(r.skill_titles.join(' · '))}<br>${esc(actor(r.actor||r.requested_by))}</div>${activeIssues.map(i=>`<span class="problem-label">● ${esc(i.title)}</span>`).join('')}${!r.issue_count&&r.issues.length?'<span class="issue-chip resolved">问题已解决</span>':''}</button>`;
    }).join('')||'<p class="empty">'+emptyMessage()+'</p>';
  }else{
    $('#run-list').innerHTML=issues.map(i=>`<button class="run-card ${i.id===state.selectedIssue?'active':''}" data-run="${i.run_id}" data-step="${i.step_id||''}" data-issue="${i.id}" aria-pressed="${i.id===state.selectedIssue}"><div class="run-topline"><span class="run-meta">${esc(category(i))}</span><span class="issue-chip ${i.status==='resolved'?'resolved':''}">${issueStatuses[i.status]}</span></div><div class="run-title">${esc(i.title)}</div><div class="run-meta">${esc(i.run.title)}<br>${esc(i.run.skill_titles.join(' · '))}</div></button>`).join('')||'<p class="empty"><strong>没有符合筛选的问题</strong>在运行或具体步骤里记录问题</p>';
  }
  $$('#run-list [data-run]').forEach(el=>el.onclick=()=>selectRun(el.dataset.run,el.dataset.step||null,el.dataset.issue||null));
}
function renderRun(){
  const r=run();if(!r){$('#run-heading').innerHTML='<p class="empty">选择一次运行</p>';$('#timeline').innerHTML='';return}
  const form=r.input_snapshot.form;
  $('#run-heading').innerHTML=`<div class="eyebrow">${esc(r.skill_titles.join(' / '))}</div><h2>${esc(r.title)}</h2><div class="heading-meta"><span class="status ${r.status}">${statuses[r.status]}</span><span>${esc(date(r.started_at||r.created_at))}</span><span>${esc(actor(r.actor||r.requested_by))}</span></div><div class="run-brief"><div><span>用户要求</span><p>${esc(compact(form.source||'没有单独保存用户原稿',135))}</p></div><div><span>${!r.output&&['running','queued','blocked'].includes(r.status)?'当前进展':'实际结果'}</span><p>${esc(compact(resultText(r),135))}</p></div></div><div class="heading-actions"><button class="button ${state.stepId?'quiet':'selected'}" id="overview">运行概览</button><button class="button quiet" id="compare-run">对照运行</button><button class="button quiet" id="mark-run-issue">记录问题</button><button class="button quiet" data-recording>过程接入</button><button class="button quiet" id="export-inspection">导出本次排查</button></div>`;
  const middle=r.steps.some(s=>['tool','input','check','artifact','progress'].includes(s.kind));
  const gap=!middle&&r.status!=='running'&&r.status!=='queued';
  $('#timeline').innerHTML=r.steps.map((s,index)=>{
    const attached=r.issues.filter(i=>i.step_id===s.id&&i.status!=='resolved');
    const gapBefore=gap&&index===r.steps.length-1&&r.steps.length>1;
    return `${gapBefore?'<div class="process-gap">这次没有记录实际执行步骤<br><button class="button quiet" data-recording>接入后续过程记录</button></div>':''}<button class="timeline-step ${s.id===state.stepId?'active':''} ${s.status}" data-step="${s.id}" aria-pressed="${s.id===state.stepId}"><span class="step-clock">${clock(s.at)}<span>${esc(kindNames[s.kind]||'运行记录')}</span>${s.skill_slug?'<span>'+esc(state.data.skills.find(x=>x.slug===s.skill_slug)?.title||s.skill_slug)+'</span>':''}${s.duration_ms!=null?'<span>'+duration(s.duration_ms)+'</span>':''}${s.status==='running'?'<span class="status running">执行中</span>':''}</span><div class="step-title">${esc(s.title)}</div><div class="step-summary">${esc(compact(s.error||s.reason||s.summary||(typeof s.output==='string'?s.output:JSON.stringify(s.output))))}</div>${attached.map(i=>'<span class="step-issue-link">● '+esc(i.title)+'</span>').join('')}</button>`;
  }).join('')||'<p class="empty">还没有步骤记录</p>';
  $('#export-inspection').onclick=openExport;
  $('#overview').onclick=()=>selectRun(r.id);$('#compare-run').onclick=()=>openComparison();$('#mark-run-issue').onclick=()=>openIssue(null,null);
  $$('#timeline [data-step]').forEach(b=>b.onclick=()=>selectRun(r.id,b.dataset.step));
  $$('[data-recording]').forEach(b=>b.onclick=openRecording);
}
function formatInput(inputs){
  if(!inputs||!Object.keys(inputs).length)return '<p class="minor">这一步没有单独记录输入</p>';
  return '<dl class="input-list">'+Object.entries(inputs).filter(([k,v])=>v!==''&&v!=null).map(([k,v])=>`<div class="input-row"><dt>${esc(fieldNames[k]||k)}</dt><dd>${esc(typeof v==='object'?JSON.stringify(v,null,2):values[v]||v)}</dd></div>`).join('')+'</dl>';
}
function requirementHTML(r){return formatInput(r.input_snapshot.form)+`<div class="minor">输入版本 ${r.input_revision} · 运行开始时的原稿</div>`}
function skillTraceHTML(r){return r.skill_trace.map(t=>`<article class="skill-trace"><div class="trace-title"><strong>${esc(t.title)}</strong><button class="button quiet" data-snapshot="${t.slug}">查看本次正文</button></div><div class="minor">${esc(t.slug)} · ${esc(t.version||t.sha256.slice(0,8))}</div><p>${esc(t.reason||'没有单独记录调用原因')}</p><div class="minor">${t.read_steps.length?'已记录 '+t.read_steps.length+' 次调用':t.context_included?'上下文已返回该 Skill 正文':'没有单独的正文读取记录'}${t.body_changed?' · 正文已有新版本':''}${t.references_changed?' · 参考已有变化':''}</div>${t.references.length?`<details><summary>${t.references.length} 个随版本保存的参考 · ${t.references.filter(x=>x.read_steps.length).length} 个有单独读取记录</summary>${t.references.map(ref=>`<div class="reference-row"><span>${esc(ref.name)}</span><span class="minor">${ref.read_steps.length?'单独读取 '+ref.read_steps.length+' 次':t.context_included?'随上下文返回':'只有快照记录'}</span></div>`).join('')}</details>`:'<div class="minor">没有随版本保存的参考文件</div>'}</article>`).join('')}
function problemCard(i){return `<article class="problem-card ${i.status==='resolved'?'resolved':''}"><div class="problem-state">${esc(category(i))} · ${issueStatuses[i.status]} · ${i.source==='record'?'运行记录提取':i.source==='agent'?'Agent 记录':'人工记录'}</div><h3>${esc(i.title)}</h3>${i.expected?'<p><span class="minor">希望怎样</span><br>'+esc(i.expected)+'</p>':''}${i.actual||i.description?'<p><span class="minor">实际怎样</span><br>'+esc(compact(i.actual||i.description,400))+'</p>':''}${['basis','cause','fix'].filter(k=>i[k]).map(k=>'<p><span class="minor">'+({basis:'判断依据',cause:'原因',fix:'改法'}[k])+'</span><br>'+esc(i[k])+'</p>').join('')}${i.comparison_run_id?'<p class="minor">已关联对照运行</p>':''}<div class="problem-actions">${i.step_id&&i.step_id!==state.stepId?`<button class="button" data-issue-step="${i.step_id}" data-issue-id="${i.id}">定位步骤</button>`:''}<button class="button" data-edit-issue="${i.id}">补充与修改</button>${i.status==='open'?`<button class="button" data-issue-id="${i.id}" data-issue-status="working">开始处理</button>`:''}<button class="button" data-issue-id="${i.id}" data-issue-status="${i.status==='resolved'?'open':'resolved'}">${i.status==='resolved'?'重新打开':'标记已解决'}</button><button class="button" data-compare-issue="${i.id}">对照运行</button></div></article>`}
function filesHTML(files){return files.map(f=>f.exists?`<a class="file-link" href="${f.url}" target="_blank" rel="noreferrer">${esc(f.name)} <span class="minor">${esc(f.type)}</span></a>`:`<div class="problem-label">文件不存在：${esc(f.name)}</div>`).join('')}
function videoProblemHTML(r,i){
  if(i?.position_seconds==null)return '';
  const videos=r.files.filter(f=>f.exists&&f.type.startsWith('video/'));
  const video=videos.find(f=>f.id===i.file_id)||(videos.length===1?videos[0]:null);if(!video)return '';
  const p=i.position_seconds,before=Math.max(0,p-.2),after=p+.2;
  return `<section class="detail-section"><h3>问题关联画面 · ${p} 秒</h3><div class="frame-strip"><figure><img src="${video.url}/frame?at=${before}" alt="${before.toFixed(1)} 秒画面"><figcaption>${before.toFixed(1)} 秒 · 之前</figcaption></figure><figure><img src="${video.url}/frame?at=${after}" alt="${after.toFixed(1)} 秒画面"><figcaption>${after.toFixed(1)} 秒 · 之后</figcaption></figure></div><details><summary>播放视频 · 定位 ${p} 秒</summary><video id="run-video" controls preload="metadata" src="${video.url}#t=${p}" aria-label="${esc(video.name)}"></video></details><div class="minor">${esc(video.name)}</div></section>`;
}
function renderDetail(){
  const r=run(),s=step();$('#copy-analysis').disabled=!r;$('#detail-heading').textContent=s?'步骤详情':'运行概览';
  if(!r){$('#step-detail').innerHTML='<p class="empty">选择一次运行</p>';return}
  const selected=issue(state.selectedIssue);
  const issues=selected?[selected]:s?r.issues.filter(i=>i.step_id===s.id):matchingIssues(r);
  const issueHTML=`<section class="detail-section"><header><h3>${s?'这一步的问题':'本次发现的问题'}</h3><button class="button quiet" id="mark-detail-issue">${s?'这一步有问题':'记录问题'}</button></header>${issues.map(problemCard).join('')||'<p class="minor">看到与要求不符的地方，可以直接记录</p>'}</section>`;
  if(!s){
    $('#step-detail').innerHTML=`${selected?issueHTML+videoProblemHTML(r,selected):''}${!selected?issueHTML:''}<section class="detail-section"><h3>实际用了哪些 Skill</h3>${skillTraceHTML(r)}</section><details class="detail-section"><summary>完整用户要求与输入 · 版本 ${r.input_revision}</summary>${requirementHTML(r)}</details><details class="detail-section"><summary>${!r.output&&['running','queued','blocked'].includes(r.status)?'完整当前进展':'完整实际结果'}</summary><pre class="content-box">${esc(resultText(r))}</pre></details><section class="detail-section"><h3>输入参考</h3>${r.input_snapshot.references.length?formatInput({references:r.input_snapshot.references}):'<p class="minor">没有单独登记输入参考</p>'}</section>${r.files.length?'<details class="detail-section"><summary>本次关联文件 · '+r.files.length+'</summary>'+filesHTML(r.files)+'</details>':''}`;
  }else{
    const parent=r.steps.find(x=>x.id===s.parent_step_id);
    const stepInfo={...(s.skill_slug?{'关联 Skill':s.skill_slug}:{}),...(parent?{'上游步骤':parent.title}:{}),...(s.reason?{'本步目的':s.reason}:{}),...(s.path?{'读取路径':s.path,'版本指纹':s.sha256}:{}),...(s.expected?{'预期结果':s.expected}:{}),...s.inputs};
    $('#step-detail').innerHTML=`<div class="eyebrow">${esc(kindNames[s.kind]||'运行步骤')}</div><div class="detail-title">${esc(s.title)}</div><div class="detail-meta">${clock(s.at)} · ${esc(actor(s.actor))}${s.duration_ms!=null?' · 耗时 '+duration(s.duration_ms):''}${s.outcome?' · '+(s.outcome==='different'?'结果不符':'符合本次检查'):''}</div>${selected?issueHTML+videoProblemHTML(r,selected):''}<section class="detail-section"><h3>输入与本步目的</h3><div class="content-box">${formatInput(stepInfo)}</div></section>${s.error?`<section class="detail-section"><h3>错误${s.exit_code!=null?' · 返回码 '+s.exit_code:''}</h3><pre class="content-box error">${esc(s.error)}</pre></section>`:''}<section class="detail-section"><h3>返回与实际结果${s.exit_code!=null?' · 返回码 '+s.exit_code:''}</h3><pre class="content-box">${esc(typeof s.output==='string'?(s.output||s.summary||'这一步没有记录返回内容'):JSON.stringify(s.output,null,2))}</pre></section>${!selected?issueHTML:''}${r.files.length?'<details class="detail-section"><summary>本次关联文件 · '+r.files.length+'</summary>'+filesHTML(r.files)+'</details>':''}<details><summary>本步原始记录</summary><pre>${esc(JSON.stringify(s,null,2))}</pre></details>`;
  }
  $('#mark-detail-issue').onclick=()=>openIssue(null,s?.id||null);
  $$('[data-issue-status]').forEach(b=>b.onclick=()=>updateIssue(b.dataset.issueId,{status:b.dataset.issueStatus}));
  $$('[data-edit-issue]').forEach(b=>b.onclick=()=>openIssue(b.dataset.editIssue));
  $$('[data-compare-issue]').forEach(b=>b.onclick=()=>openComparison(b.dataset.compareIssue));
  $$('[data-issue-step]').forEach(b=>b.onclick=()=>selectRun(r.id,b.dataset.issueStep,b.dataset.issueId));
  $$('[data-snapshot]').forEach(b=>b.onclick=()=>openSnapshot(b.dataset.snapshot));
  const player=$('#run-video');if(player&&selected?.position_seconds!=null)player.addEventListener('loadedmetadata',()=>{if(Number.isFinite(player.duration))player.currentTime=Math.min(selected.position_seconds,Math.max(0,player.duration-.1))},{once:true});
}
async function openSnapshot(slug){
  try{const doc=await api('/api/runs/'+run().id+'/skills/'+slug);$('#snapshot-title').textContent='本次 Skill 快照 · '+(state.data.skills.find(s=>s.slug===slug)?.title||slug);$('#snapshot-content').innerHTML=`<p class="minor">${esc(doc.path)} · ${esc(doc.sha256)}</p><pre class="snapshot-body">${esc(doc.body)}</pre><h3>随版本保存的参考</h3>${doc.references.map(ref=>`<details class="snapshot-ref"><summary>${esc(ref.name)} · ${esc(ref.sha256.slice(0,8))}</summary><p class="minor">${esc(ref.path)}</p><pre>${esc(ref.body)}</pre></details>`).join('')}`;$('#snapshot-dialog').showModal()}catch(error){toast(error.message)}
}
async function updateIssue(id,patch){try{await api('/api/issues/'+id,'PATCH',{actor:who,...patch});await load(true);toast('问题记录已保存')}catch(error){toast(error.message)}}
function openIssue(id=null,stepId=state.stepId){
  const r=run();if(!r)return;const i=issue(id);state.editIssue=id;state.issueStep=i?.step_id||stepId;
  $('#issue-dialog-title').textContent=i?'补充与修改问题':'记录问题';$('#issue-location').textContent=r.title+(state.issueStep?' / '+r.steps.find(s=>s.id===state.issueStep)?.title:' / 整次运行');
  for(const key of ['title','expected','actual','basis','cause','fix'])$('#issue-'+key).value=i?.[key]||(key==='actual'?i?.description||'':'');
  $('#issue-category').innerHTML=Object.entries(state.data.categories).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');$('#issue-category').value=i?.category||'output';
  $('#issue-skill').innerHTML='<option value="">整次运行</option>'+r.skills.map(s=>`<option value="${s.slug}">${esc(s.slug)}</option>`).join('');$('#issue-skill').value=i?.related_skill||'';
  $('#issue-file').innerHTML='<option value="">不关联文件</option>'+r.files.map(f=>`<option value="${f.id}">${esc(f.name)}</option>`).join('');$('#issue-file').value=i?.file_id||'';$('#issue-position').value=i?.position_seconds??'';
  $('#issue-dialog').showModal();$('#issue-title').focus();
}
$('#issue-form').onsubmit=async e=>{
  e.preventDefault();const r=run(),body={actor:who,run_id:r.id,step_id:state.issueStep,category:$('#issue-category').value,related_skill:$('#issue-skill').value,file_id:$('#issue-file').value};
  for(const key of ['title','expected','actual','basis','cause','fix'])body[key]=$('#issue-'+key).value.trim();
  body.description=body.actual;body.position_seconds=$('#issue-position').value===''?null:Number($('#issue-position').value);
  try{const saved=await api('/api/issues'+(state.editIssue?'/'+state.editIssue:''),state.editIssue?'PATCH':'POST',body);$('#issue-dialog').close();state.selectedIssue=saved.id;await load(true);selectRun(r.id,state.issueStep,saved.id);toast('问题已保存')}catch(error){toast(error.message)}
};
function comparisonPanel(r,other){
  const a=r.input_snapshot.form,b=other.input_snapshot.form;
  const fields=[...new Set([...Object.keys(a),...Object.keys(b)])].filter(k=>a[k]!==b[k]);
  const versions=r.skill_trace.map(t=>{const old=other.skill_trace.find(x=>x.slug===t.slug);return `<div class="diff-field ${!old||old.snapshot_id!==t.snapshot_id||old.sha256!==t.sha256?'changed':''}"><strong>${esc(t.title)}</strong> · ${esc(t.sha256.slice(0,8))}<br><span class="minor">${esc(t.reason||'没有记录调用原因')} · ${t.references.length} 个参考</span>${t.references.map(ref=>'<div class="minor">'+esc(ref.name)+' · '+esc(ref.sha256.slice(0,8))+'</div>').join('')}</div>`}).join('');
  return `<section><div class="minor">${esc(date(r.started_at||r.created_at))} · ${esc(actor(r.actor||r.requested_by))}</div><h3>${esc(r.title)}</h3><div class="detail-section"><h3>用户要求变化</h3>${fields.length?fields.map(k=>`<div class="diff-field changed"><span class="minor">${esc(fieldNames[k]||k)}</span><br>${esc(a[k]||'空')}</div>`).join(''):'<div class="minor">两次运行的表单要求相同</div>'}${JSON.stringify(r.input_snapshot.references)!==JSON.stringify(other.input_snapshot.references)?'<div class="diff-field changed">输入参考有变化<pre>'+esc(JSON.stringify(r.input_snapshot.references,null,2))+'</pre></div>':''}${r.input_snapshot.draft!==other.input_snapshot.draft?'<div class="diff-field changed">输入草稿有变化<pre>'+esc(r.input_snapshot.draft||'空')+'</pre></div>':''}</div><div class="detail-section"><h3>Skill 与规则版本</h3>${versions}</div><div class="detail-section"><h3>执行过程</h3>${r.steps.map(s=>`<div class="compare-step"><span class="minor">${clock(s.at)} · ${esc(kindNames[s.kind]||'运行记录')} ${s.duration_ms!=null?'· '+duration(s.duration_ms):''}</span><strong>${esc(s.title)}</strong><div>${esc(compact(s.error||s.reason||s.summary||s.output,140))}</div></div>`).join('')}</div><div class="detail-section"><h3>${['running','queued'].includes(r.status)?'当前进展':'实际结果'}</h3><pre class="content-box">${esc(resultText(r))}</pre></div><div class="detail-section"><h3>已记录的问题</h3>${r.issues.map(i=>'<p>'+esc(i.title)+' · '+issueStatuses[i.status]+'</p>').join('')||'<p class="minor">没有记录问题</p>'}</div>${r.files.length?'<details><summary>关联文件 · '+r.files.length+'</summary>'+filesHTML(r.files)+'</details>':''}</section>`;
}
function openComparison(issueId=null){
  const r=run();if(!r)return;state.compareIssue=issueId;
  const options=state.data.runs.filter(x=>x.id!==r.id).sort((a,b)=>(b.task_id===r.task_id)-(a.task_id===r.task_id));if(!options.length){toast('还没有其他运行可对照');return}
  const chosen=issue(issueId)?.comparison_run_id||r.related_run_ids.find(id=>state.data.runs.find(x=>x.id===id)?.started_at>r.started_at)||r.related_run_ids[0]||options[0].id;
  $('#compare-problem').textContent=issueId?'对照问题：'+issue(issueId).title:'对照用户要求、Skill 版本、过程与结果';
  $('#compare-select').innerHTML=options.map(x=>`<option value="${x.id}" ${chosen===x.id?'selected':''}>${esc(x.title)} · ${esc(date(x.started_at||x.created_at))}${x.task_id===r.task_id?' · 同一任务':''}</option>`).join('');renderComparison();$('#compare-dialog').showModal();
}
function renderComparison(){const a=run(),b=state.data.runs.find(x=>x.id===$('#compare-select').value);if(!a||!b)return;$('#comparison').innerHTML=comparisonPanel(a,b)+comparisonPanel(b,a);$('#link-comparison').hidden=!state.compareIssue}
$('#compare-select').onchange=renderComparison;
$('#link-comparison').onclick=async()=>{await updateIssue(state.compareIssue,{comparison_run_id:$('#compare-select').value});$('#compare-dialog').close()};
function recordingText(){const r=visibleRuns().some(x=>x.id===state.runId)?run():null,skills=r?.skills.map(s=>s.slug)||[$('#skill-filter').value||'seedance-prompts'];return `11 个 Seedance Skill 共用此入口；沿真实任务记录，不重做历史操作。\nCLI：python3 skills/seedance-prompts/runtime/studio/diagnostics.py start --task ${r?.task_id||'<真实task_id>'} ${skills.map(s=>'--skill '+s).join(' ')}\n2. context --task ${r?.task_id||'<task_id>'} --run <返回的run_id>\n3. read-skill --run <run_id> --skill <实际Skill> --reason "为什么在这一步使用它"\n   读取具体参考时加 --reference <快照内参考路径>；专项接续加 --parent-step <上游step_id>。\n4. exec --run <run_id> --title "具体工具步骤" -- <原工具命令与参数>\n   原生工具和结果检查用 step-start/step-finish；检查时保存 --expected 与 --outcome matched/different。\n5. issue --json <问题JSON>，保存 category、expected、actual、basis、cause、fix；修改用 --id <issue_id>。\n6. finish --run <run_id> --status completed --summary "实际完成内容" --output-file <结果文件>\n\n完整字段见本工作台 AGENT.md。所有执行沿本次任务的原授权；记录实际动作和结果。`}
function openRecording(){$('#recording-command').textContent=recordingText();$('#recording-dialog').showModal()}
async function copy(text){try{await navigator.clipboard.writeText(text);toast('已复制，可直接交给 Agent')}catch{toast('复制未完成，请使用浏览器的复制功能')}}
$('#copy-recording').onclick=()=>copy(recordingText());
function inspectionURL(){const query=new URLSearchParams();if(state.stepId)query.set('step',state.stepId);if(state.selectedIssue)query.set('issue',state.selectedIssue);return '/api/runs/'+run().id+'/inspect'+(query.size?'?'+query:'')}
async function openExport(){try{const data=await api(inspectionURL());$('#export-json').value=JSON.stringify(data,null,2);$('#download-inspection').href=inspectionURL()+(inspectionURL().includes('?')?'&':'?')+'download=1';$('#download-inspection').download=run().id+'_排查.json';$('#export-dialog').showModal()}catch(error){toast(error.message)}}
$('#copy-export').onclick=()=>copy($('#export-json').value);
$('#copy-analysis').onclick=()=>{const r=run();if(!r)return;copy(`请排查这次 Skill 使用，从具体输入或步骤指出偏离用户要求的地方，并给出改法。\n\n本机 CLI（不依赖网页服务）：\npython3 skills/seedance-prompts/runtime/studio/diagnostics.py inspect --run ${r.id}${state.stepId?' --step '+state.stepId:''}${state.selectedIssue?' --issue '+state.selectedIssue:''}\n\nHTTP 只读入口：${location.origin}${inspectionURL()}\n\n返回仅含本次运行、原要求、过程、问题和锁定的 Skill 正文及参考。保留已有文件和手改，缺少的步骤直接指出；不要重做外部动作。将发现用 issue --json <文件> 写回该 run；已有问题用 --id 更新 expected、actual、basis、cause、fix。`)};
$$('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
$$('dialog').forEach(d=>d.addEventListener('close',()=>d.querySelectorAll('video').forEach(v=>v.pause())));
function setMode(mode){state.mode=mode;$('#view-runs').classList.toggle('active',mode==='runs');$('#view-issues').classList.toggle('active',mode==='issues');$('#view-runs').setAttribute('aria-pressed',mode==='runs');$('#view-issues').setAttribute('aria-pressed',mode==='issues');renderList()}
$('#view-runs').onclick=()=>setMode('runs');$('#view-issues').onclick=()=>setMode('issues');
function applyFilters(){
  const rows=visibleRuns();renderList();
  if(!rows.length){$('#run-heading').innerHTML='<p class="empty">'+emptyMessage()+'</p><button class="button quiet" data-empty-recording>查看统一接入方式</button>';$('#timeline').innerHTML='';$('#step-detail').innerHTML='<p class="empty">选择其他筛选条件，或接入该 Skill 的下一次实际运行</p>';$('#copy-analysis').disabled=true;$('#run-heading [data-empty-recording]').onclick=openRecording;return}
  if(!rows.some(r=>r.id===state.runId))selectRun(rows[0].id);else{renderRun();renderDetail()}
}
for(const id of ['search','skill-filter','category-filter','issue-status-filter','time-filter','only-issues','show-tests'])$('#'+id).addEventListener(id==='search'?'input':'change',()=>{state.selectedIssue=null;const url=new URL(location.href);url.searchParams.delete('issue');history.replaceState(null,'',url);applyFilters()});
async function load(force=false){
  const request=++state.request;
  try{
    const data=await api('/api/monitor');if(request<state.applied)return;state.applied=request;
    const signature=JSON.stringify([data.sequence,data.runs.map(r=>[r.id,r.status,r.skill_trace,r.files.map(f=>[f.id,f.exists,f.size])])]);
    const changed=signature!==state.signature;state.data=data;state.signature=signature;
    $('#sync-state').textContent='本机同步 · '+clock(data.read_at);
    if(!$('#skill-filter').dataset.loaded){$('#skill-filter').insertAdjacentHTML('beforeend',data.skills.map(s=>`<option value="${s.slug}">${esc(s.title)} · ${data.runs.filter(r=>r.skills.some(x=>x.slug===s.slug)).length}</option>`).join(''));$('#category-filter').insertAdjacentHTML('beforeend',Object.entries(data.categories).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join(''));$('#skill-filter').dataset.loaded='1'}
    $$('#skill-filter option[value]').forEach(o=>{const skill=data.skills.find(s=>s.slug===o.value);if(skill)o.textContent=skill.title+' · '+data.runs.filter(r=>r.skills.some(s=>s.slug===o.value)).length});
    if(!run()){const initial=visibleRuns()[0];if(initial)selectRun(initial.id,state.stepId,state.selectedIssue);else applyFilters()}
    else if(changed||force){if(state.stepId&&!run().steps.some(s=>s.id===state.stepId))state.stepId=null;const top=$('#step-detail').scrollTop;applyFilters();$('#step-detail').scrollTop=top}
  }catch(error){$('#sync-state').textContent='连接中断';if(!state.data)$('#run-list').innerHTML='<p class="empty error-message">'+esc(error.message)+'</p>';else if(force)toast(error.message)}
}
$('#refresh').onclick=()=>load(true);
load(true);setInterval(()=>load(),2000);
