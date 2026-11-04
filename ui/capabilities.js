'use strict';
(() => {
  const nodes=window.SK005_NODES;
  const mergedNodes={B03:'B02',B05:'B04',OUTPUT:'B04'};
  const visibleNode=n=>n.group!=='library'&&!Object.hasOwn(mergedNodes,n.id);
  const groups={source:'来源与剧情',character:'角色与物料',script:'剧本与镜头',gen:'生成',post:'后期与A段交付',b:'接 B 与输出',library:'素材库',output:'输出专项'};
  const $=id=>document.getElementById(id);
  const dialog=$('capability-dialog'),overview=$('stage-overview');
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const href=p=>p.split('/').map(encodeURIComponent).join('/');
  let current=0,lastTrigger=null;
  function pauseVideo(){dialog.querySelectorAll('video').forEach(v=>v.pause());}
  function storyboardHTML(){
    const data=nodes.find(n=>n.storyboard)?.storyboard_data;
    const rows=data?.rows||[];
    return `<section class="director-document" aria-label="分镜导演稿案例"><div class="director-heading"><span>分镜导演稿 · 案例</span><h3>${esc(data.title)}</h3><p>${esc(data.intro)}</p></div><div class="director-scroll" tabindex="0" aria-label="可横向滚动的分镜表"><table class="director-table"><thead><tr>${['镜号','对照参考','分镜画面','景别','运镜','原文案','改编文案｜画面与动作','改编文案｜对白','声音','时长'].map((h,i)=>`<th class="dc-${i}">${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><th>${r[0]}</th><td class="reference">${r[1]?`<img src="${href(r[1])}" alt="${esc(r[0])} 来源参考" loading="lazy"><small>${esc(r[10])}</small>`:''}</td><td>${r[7]?`<img src="${href(r[7])}" alt="${esc(r[0])} 实际画面" loading="lazy">`:''}</td><td>${esc(r[6])}</td><td>${esc(r[9])}</td><td class="original">${esc(r[8])}</td><td class="adapted">${r[2]}</td><td class="adapted">${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td></tr>`).join('')}</tbody></table></div><p class="director-foot">${esc(data.foot)}</p></section>`;
  }
  function visualHTML(v){return v.type==='video'?`<figure class="node-media"><video controls playsinline preload="none"${v.poster?` poster="${href(v.poster)}"`:""}><source src="${href(v.path)}" type="video/mp4"></video><figcaption>${esc(v.caption)}</figcaption></figure>`:`<figure class="node-capture"><a href="${href(v.path)}" target="_blank" rel="noopener"><img src="${href(v.path)}" alt="${esc(v.caption)}" loading="lazy"></a><figcaption>${esc(v.caption)} · 点击查看原图</figcaption></figure>`;}
  function caseFactsHTML(n){
    const rows=[['输入','input'],['操作','action'],['产出','output'],['边界','boundary']].filter(([,k])=>n[k]);
    if(!rows.length)return '';
    return `<dl class="case-facts">${rows.map(([label,k])=>`<dt>${label}</dt><dd>${esc(n[k])}</dd>`).join('')}</dl>`;
  }
  const SKILL_NOTES={
    'seedance-paid-skit-production-pipeline':'加载当前节点合同、校验输入、记录证据与写回状态',
    'seedance-douyin-video':'下载抖音原片、提取文案、按需转写',
    'paid-skit-copywriting':'仅偏心题材的独立创作兼容入口',
    'paid-skit-storyboard':'创意预演、完整导演稿与关键镜头优化接口',
    'naruto-favoritism-skit-generator':'偏心题材的独立剧情/剧本分支',
    'paid-skit-character-format':'角色库字段、编号与版本记录',
    'paid-skit-asset-bridge':'角色/素材原件入库、查重、反链与回读',
    'paid-skit-character-sheet':'正视母版与三视图的生成/修正规则',
    'imagegen':'生图/编辑执行器，仅需要生成时使用',
    'paid-skit-video-prompts':'视频提示词与参考图绑定',
    'rongyao-ai-generator':'荣耀生成：模型、额度、提交、下载、回查',
    'rongyao-keyring':'荣耀登录态与钥匙包恢复',
    'rongyao-data-stack':'荣耀工具与数据栈维护',
    'rongyao-operations':'计划、账本、SHA 与任务回查',
    'rongyao-http-readonly':'荣耀只读查询与分页',
    'dreamina-canvas-cli':'即梦画布/生成分支',
    'paid-skit-premiere':'PR 工程剪辑与原生导出',
    'rongyao-material-upload':'成片命名、字段、分片上传与回查',
    'FFmpeg':'接片、转码与技术检查',
    'rongyao-material-analysis':'素材表现与 ROI 分析口径',
    'rongyao-video-upload':'成片命名、A/B 接片与快速上传',
    'rongyao-dashboard-filter-finder':'新素材2.0 按项目/日期/筛选查询与导出',
    'rongyao-material-performance':'素材消耗、ROI 与角色方向分析',
    'rongyao-http-upload':'无浏览器 HTTP 上传与登录恢复',
  };
  const baseName=s=>s.replace(/（.*?）/g,'').trim();
  const PACKAGE_RULES=new Set(['paid-skit-copywriting','paid-skit-storyboard','paid-skit-character-format','paid-skit-asset-bridge','paid-skit-character-sheet','paid-skit-video-prompts']);
  const LOCAL_PACKAGES=new Set(['rongyao-ai-generator','rongyao-operations','rongyao-http-readonly','rongyao-material-analysis','rongyao-dashboard-filter-finder']);
  function skillSource(name){
    if(name==='FFmpeg')return '外部工具，需自行安装';
    if(name==='seedance-douyin-video')return '包内含seedance-douyin-video及旧名兼容入口；按当前阶段安装';
    if(PACKAGE_RULES.has(name))return '交付包内的工作流规则适配包；当前为本地候选';
    if(name==='imagegen')return 'Codex 系统 Skill；交付包清单包含';
    if(name==='naruto-favoritism-skit-generator')return '独立项目 Skill；交付包清单包含';
    if(LOCAL_PACKAGES.has(name))return '本机项目 Skill；交付包清单包含，发布状态以各自记录为准';
    return '交付包清单包含；以实际安装与当前合同为准';
  }
  function stepRoleHTML(role,skills){
    const names=(skills||[]).map(baseName).sort((a,b)=>b.length-a.length);
    let html='',pos=0;
    while(pos<role.length){
      const name=names.find(x=>role.startsWith(x,pos));
      if(name){html+=`<code>${esc(name)}</code>`;pos+=name.length;}
      else{html+=esc(role[pos]);pos++;}
    }
    return html;
  }
  function stepsHTML(n){
    if(n.steps_detail?.length){
      const items=n.steps_detail.map(step=>`<li><strong>${esc(step.title)}</strong><p>${esc(step.description)}</p>${step.dimensions?.length?`<p><strong>拆解维度：</strong></p><ul>${step.dimensions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${step.method?`<p><strong>核对方法：</strong>${esc(step.method)}</p>`:''}${step.role?`<p class="step-role">${stepRoleHTML(step.role,n.skills)}</p>`:''}${step.result?`<p class="step-result"><strong>得到：</strong>${esc(step.result)}</p>`:''}${step.example?`<p>${esc(step.example_label||'示例：')}</p><table><thead><tr>${(step.example_headers||['时间','画面或声音']).map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${step.example.map(row=>`<tr>${row.map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>${step.example_note?`<p>${esc(step.example_note)}</p>`:''}${step.example_insights?.map(item=>`<p><strong>${esc(item[0])}：</strong>${esc(item[1])}</p>`).join('')||''}`:''}</li>`).join('');
      return `<section class="node-steps steps-detail"><h4>操作步骤</h4><ol>${items}</ol>${n.steps_note?`<p>${esc(n.steps_note)}</p>`:''}</section>`;
    }
    if(!n.steps?.length)return '';
    return `<section class="node-steps"><h4>操作步骤</h4><ol>${n.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></section>`;
  }
  function skillsHTML(n){
    if(n.hide_skill_list||!n.skills?.length)return '';
    return `<section class="node-skills"><h4>使用工具</h4><ul>${n.skills.map(x=>`<li><code>${esc(x)}</code><span>${esc(SKILL_NOTES[baseName(x)]||'按当前节点合同执行')}；来源：${esc(skillSource(baseName(x)))}</span></li>`).join('')}</ul></section>`;
  }
  function envHTML(env){
    const items=(env||[]).flatMap(x=>String(x).split(/[；;／/]/)).map(x=>x.trim()).filter(Boolean);
    if(!items.length)return '';
    const tagged=items.map(x=>{
      let tag='条件',label=x,note='按合同原文';
      if(SKILL_NOTES[baseName(x)]){tag='Skill';note=baseName(x)==='seedance-douyin-video'?'包内正式名及旧名兼容入口': '检查实际安装';}
      else if(/转写/.test(x)){tag='可选';label='语音转写工具';note='没有就人工核对';}
      else if(/ffprobe|ffmpeg/i.test(x)){tag='依赖';note='随 FFmpeg 安装';}
      else if(/premiere|py-premiere/i.test(x)){tag='依赖';note='需本机 Premiere';}
      else if(/node|lark-cli|dreamina/i.test(x)){tag='依赖';note='需本机安装';}
      else if(/荣耀上传工具/.test(x)){tag='Skill';note='上传阶段安装';}
      else if(/上传工具/.test(x)){tag='依赖';note='需上传工具';}
      else if(/writer|scope|授权/.test(x)){tag='条件';note='需相应授权';}
      return `<li><span class="env-tag">${tag}</span><span class="env-name">${esc(label)}</span><small>${note}</small></li>`;
    }).join('');
    return `<ul class="env-list">${tagged}</ul><p class="env-note">Skill 与依赖的安装状态以实际环境为准。</p>`;
  }
  function contractHTML(n){
    const c=n.contract;if(!c)return '';
    const list=a=>a?.length?`<ul>${a.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'';
    const rows=[['目标',esc(c.goal||'')],['交付物',list(c.deliver)],['环境与依赖',envHTML(c.environment)]];
    const body=rows.filter(([,v])=>v).map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('');
    return `<section class="node-contract" aria-label="本节点合同要求"><h4>本节点要求</h4><p class="contract-hint">完成本节点交付，核对内容与版本。</p><dl>${body}</dl></section>`;
  }
  function nodeHTML(n){
    const siblings=nodes.filter(x=>x.group===n.group&&visibleNode(x));
    const nav=`<nav class="node-nav" aria-label="本能力下的小节点">${siblings.map(x=>`<button type="button" class="node-jump" data-jump="${x.id}" aria-pressed="${x.id===n.id}">${esc(x.id)} · ${esc(x.title)}</button>`).join('')}</nav>`;
    let media='';
    if(n.visuals?.length>1)media=`<div class="media-switch" role="group" aria-label="选择文件">${n.visuals.map((v,i)=>`<button class="ui-btn" data-media-index="${i}" aria-pressed="${i===0}">${esc(v.caption)}</button>`).join('')}</div><div id="chosen-media">${visualHTML(n.visuals[0])}</div>`;
    else if(n.visuals?.length)media=visualHTML(n.visuals[0]);
    return `${nav}${contractHTML(n)}${stepsHTML(n)}${skillsHTML(n)}`;
  }
  function render(index){
    pauseVideo();current=index;const n=nodes[index];
    $('detail-title').textContent=n.id+' · '+n.title;
    $('detail-range').textContent='买量管线 / '+groups[n.group];
    $('detail-intro').textContent=groups[n.group]+' · 操作与交付材料';
    overview.innerHTML=nodeHTML(n);
    $('prev-stage').disabled=adjacentIndex(index,-1)<0;$('next-stage').disabled=adjacentIndex(index,1)<0;
    $('stage-position').textContent=n.id==='OUTPUT'?'独立输出专项 · 不计入24节点':`${index+1} / 24 个生产节点`;
    dialog.scrollTop=0;
  }
  function openNode(id,trigger){
    const index=nodes.findIndex(n=>n.id===(mergedNodes[id]||id));if(index<0)return;
    if(!dialog.open){lastTrigger=trigger||document.activeElement;dialog.showModal();document.body.classList.add('modal-open');}
    render(index);$('close-dialog').focus();
  }
  document.querySelectorAll('.case-open').forEach(btn=>btn.addEventListener('click',()=>openNode(btn.dataset.node,btn)));
  $('close-dialog').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',e=>{
    if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}
    const jump=e.target.closest('[data-jump]');
    if(jump){render(nodes.findIndex(n=>n.id===jump.dataset.jump));overview.querySelector(`[data-jump="${nodes[current].id}"]`)?.focus();}
    const mediaButton=e.target.closest('[data-media-index]');
    if(mediaButton){pauseVideo();const i=Number(mediaButton.dataset.mediaIndex);$('chosen-media').innerHTML=visualHTML(nodes[current].visuals[i]);overview.querySelectorAll('[data-media-index]').forEach(b=>b.setAttribute('aria-pressed',String(b===mediaButton)));}
  });
  dialog.addEventListener('close',()=>{pauseVideo();document.body.classList.remove('modal-open');if(lastTrigger?.isConnected)lastTrigger.focus();});
  function adjacentIndex(index,direction){for(let i=index+direction;i>=0&&i<nodes.length;i+=direction)if(visibleNode(nodes[i]))return i;return -1;}
  $('prev-stage').addEventListener('click',()=>{const i=adjacentIndex(current,-1);if(i>=0){render(i);$('detail-title').focus();}});
  $('next-stage').addEventListener('click',()=>{const i=adjacentIndex(current,1);if(i>=0){render(i);$('detail-title').focus();}});
  function followHash(){const m=location.hash.match(/^#case-sk005(?:-(A\d\d|B\d\d|LIBRARY\d\d|OUTPUT))?$/);if(m)openNode(m[1]||'A01',document.querySelector('#layer-source .case-open'));}
  window.addEventListener('hashchange',followHash);followHash();
})();
