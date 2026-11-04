---
name: seedance-cinematic-director
description: 为Seedance设计空间调度、镜头、光色、连续性、关键帧及故障修复；普通单条提示词可用seedance-prompts，战斗、冲击、特效与变装进入对应专项。
license: MIT
metadata:
  version: "2.2.0+local.seedance"
  author: "wangzhang-wu"
---

# Seedance 导演与预演

先确定本次交付和素材职责，按[Seedance共用合同](../seedance-prompts/references/contract.md)处理引用、规格与执行边界。只修所需导演问题；角色、画风、剧情结果、已有资产和用户手改保持其已确认部分。

## 选择入口

普通正文可直接用[seedance-prompts](../seedance-prompts/SKILL.md)。战斗因果、接触增强、特效和变装分别交[seedance-battle-action-prompts](../seedance-battle-action-prompts/SKILL.md)、[seedance-combat-impact-prompts](../seedance-combat-impact-prompts/SKILL.md)、[seedance-vfx-prompt-writing](../seedance-vfx-prompt-writing/SKILL.md)、[seedance-outfit-transition-planning](../seedance-outfit-transition-planning/SKILL.md)；导演只补当前分支缺少的调度与摄影决定，不重做其格式和输入选择。

| 用户需要 | 只读相应资源 |
|---|---|
| A 剧情解读、B 节拍、C 视觉方案 | [导演方法](references/directing-workflow.md)对应步骤；B用[节拍模板](assets/beat-sheet-template.md)，C用[导演手册模板](assets/director-book-template.md)及[光色](references/lighting-and-color.md) |
| D 调度、分镜、机位 | [调度](references/blocking-and-staging.md)、[电影语言](references/cinematic-language.md)、[分镜模板](assets/shot-plan-template.md)；风险判定用[制作流程](references/production-workflow.md) |
| E 关键帧或故事板图 | [图像适配](references/image-model-adapters.md)、[关键帧模板](assets/keyframe-prompt-template.md)、[质检表](assets/qc-checklist.md)；先核输入模式，已有角色参考足够时不强制补图 |
| F 视频运动提示词 | [Seedance适配](references/ai-video-tool-adapters.md)、[视频模板](assets/video-prompt-template.md)；措辞问题按需查[词汇表](references/prompt-lexicon.md) |
| G 多镜头角色与场景连续性 | [连续性规则](references/continuity-bible.md) |
| H 声音、对白、配音 | [声音规则](references/sound-and-dialogue.md)、[声音计划](assets/sound-plan-template.md) |
| I 剪辑与组合 | [剪辑规则](references/editing-and-assembly.md)、[时间线模板](assets/edit-timeline-template.md) |
| J 生成失败、漂移、动作不足 | [故障索引](references/failure-modes.md)只读症状对应项；需要改稿再转F；[质检表](assets/qc-checklist.md)用于已有结果 |
| 明确导演风格 | [风格索引](references/director_styles/README.md)选实际匹配模块；仅加载所选风格 |
| 明确题材或产品镜头 | [题材](references/genre-playbooks.md)对应部分；产品再读[产品与微距](references/product-and-macro.md) |
| 完整导演制作或已采用的默认视觉集合 | [导演方法](references/directing-workflow.md)按阶段；交付范围读[原视觉集合](references/output-defaults.md) |

## 导演决定与交付

先安排人物的目的、位置、动作、接触与终态，再选能读出变化的机位、景别、光源与运镜。每镜围绕主要变化组织，有因果的动作链和多镜头均可按任务需要使用。固定机位也要明确人物/道具布局与空间层次。

需要分配画面各元素依据或处理参考冲突时读[元素与控制分工](references/element-control-contract.md)。身份、造型、布局、风格和动作各有依据，补图只解决真实控制缺口。

一条提示词请求交可复制正文；单项模式只交该产物。完整制作按已指定范围推进；输出模板是工具，不为填满模板增加镜头、图件或生成任务。生成、剪辑、实际音画与用户采用分别验收。

## 可选工作台

只有用户要求记录、从工作台排队任务续接，或当前项目已选用工作台时，才读取 `seedance-prompts` 的 `references/studio.md`，沿同一 task/run 保存进度与候选。普通创作、采集与字幕直接在当前任务交付；工作台未配置不阻塞这些工作，也不替代原项目状态。
