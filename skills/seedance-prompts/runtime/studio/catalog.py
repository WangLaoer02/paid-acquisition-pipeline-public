"""Read only the 11 approved local Seedance Skill entrypoints and linked text references."""
from pathlib import Path
import re,hashlib,datetime,json
from configuration import SKILLS_ROOT
ROOT=SKILLS_ROOT
SPECS=[
 ('seedance-prompts','通用提示词','文本','从想法或原稿开始，选择合适格式。','写作'),
 ('seedance-cinematic-director','导演与镜头','视觉','设计空间、摄影、光线与连续性。','镜头'),
 ('seedance-battle-action-prompts','战斗动作','文本','写清接近、攻防、接触与结果。','动作'),
 ('seedance-combat-impact-prompts','冲击增强','文本','只强化关键一拍的接触与受力。','冲击'),
 ('seedance-vfx-prompt-writing','特效写作','视觉','组织特效形态、触发、交互与消散。','特效'),
 ('seedance-anime-cg-reference-shot','二次元 CG','视觉','让角色、场景与动作板各司其职。','CG'),
 ('seedance-outfit-transition-planning','变装规划','视觉','沿用造型，设计触发、变化与收稳。','变装'),
 ('seedance-character-shortvideo-production','角色短视频','制作','规划角色展示、舞蹈与制作验收。','角色'),
 ('seedance-story-skit-production','故事小剧场','文本','从人物动机到完整故事与表演。','故事'),
 ('seedance-douyin-video','视频参考','参考','记录视频证据，准备受限或完整反推。','参考'),
 ('seedance-paid-skit-production-pipeline','买量短剧','制作','按原项目当前节点准备交接。','买量')]

def field(text,key):
 m=re.search(r'^[ \t]*'+re.escape(key)+r':\s*(.+)$',text,re.M)
 return m.group(1).strip().strip('"\'') if m else ''

def catalog():
 allowed=[(ROOT/s[0]).resolve() for s in SPECS];items=[]
 for slug,title,group,summary,short in SPECS:
  p=ROOT/slug/'SKILL.md'
  if not p.is_file():
   items.append(dict(slug=slug,title=title,group=group,summary=summary,short=short,available=False,path=str(p),body='',references=[]));continue
  text=p.read_text();refitems=[];seen=set()
  for match in re.finditer(r'\[[^\]\n]*\]\(([^)\n]+)\)',text):
   target=match.group(1).split('#',1)[0].strip('<>')
   if not target or re.match(r'^\w+://',target):continue
   file=(p.parent/target).resolve()
   if file in seen or file.name=='SKILL.md':continue
   seen.add(file)
   if not file.is_file() or file.suffix not in ['.md','.txt','.json'] or not any(file.is_relative_to(r) for r in allowed):continue
   body=file.read_text()
   refitems.append(dict(name=file.name,path=str(file),body=body,sha256=hashlib.sha256(body.encode()).hexdigest()))
  items.append(dict(slug=slug,title=title,group=group,summary=summary,short=short,available=True,path=str(p),body=text,description=field(text,'description'),version=field(text,'version'),sha256=hashlib.sha256(text.encode()).hexdigest(),references=refitems))
 return dict(skills=items,readAt='public-source-build',source='local',generationConnected=False)

if __name__=='__main__':
 p=Path(__file__).parent/'maker.html';text=p.read_text();data=json.dumps(catalog(),ensure_ascii=False).replace(str(ROOT) + '/', 'skills/').replace('<','\\u003c')
 text=re.sub(r'(<script id="skill-data" type="application/json">).*?(</script>)',lambda m:m.group(1)+data+m.group(2),text,flags=re.S);p.write_text(text)
 print('Updated local snapshot: 11 canonical Seedance Skills.')
