---
name: seedance-prompts
description: 编写、润色或反推Seedance视频提示词；普通单镜与多镜头直接处理，战斗、冲击、特效和变装按需转专项。仅平台操作使用原执行入口。
metadata:
  version: "1.0.0"
---

# Seedance 提示词

本地维护的通用入口。读取[输入、格式与执行边界](references/contract.md)，再选择本次需要的专项。只改用户要求的内容；已有采用稿保留其结构、参考和有效表达。

## 按任务选择

| 当前请求 | 使用方法 |
|---|---|
| 普通单镜、从图设计动作、已有正文润色 | 直接按本入口写；需要模板时读[格式与示例](references/formats.md) |
| 多镜头、完整剧情或用户指定五模块 | 读[格式与示例](references/formats.md)的对应部分；不按每句台词另开生成任务 |
| 空间调度、景别、摄影、连续性或故障诊断 | [seedance-cinematic-director](../seedance-cinematic-director/SKILL.md)，只补当前导演决策 |
| 完整交锋、攻防关系或动作因果不清 | [seedance-battle-action-prompts](../seedance-battle-action-prompts/SKILL.md) |
| 动作已成立，只增强接触、受力或冲击帧 | [seedance-combat-impact-prompts](../seedance-combat-impact-prompts/SKILL.md) |
| 特效的轮廓、触发、传播、交互或消散 | [seedance-vfx-prompt-writing](../seedance-vfx-prompt-writing/SKILL.md) |
| 变装 | [seedance-outfit-transition-planning](../seedance-outfit-transition-planning/SKILL.md)，保留精简@图N格式 |
| 舞蹈、服装、动作展示的制作与验收 | [seedance-character-shortvideo-production](../seedance-character-shortvideo-production/SKILL.md) |
| 三视图＋场景＋动作板的二次元CG短镜头 | [seedance-anime-cg-reference-shot](../seedance-anime-cg-reference-shot/SKILL.md) |
| 从完整故事推进到故事板及提示词 | [seedance-story-skit-production](../seedance-story-skit-production/SKILL.md) |
| 抖音来源采集、观察视频后反推 | `seedance-douyin-video`（seedance-douyin-video，`SKILL.md`，按已安装 Skill 目录定位）先取得证据，再回到本地格式 |
| 已登记的买量项目 | [seedance-paid-skit-production-pipeline](../seedance-paid-skit-production-pipeline/SKILL.md)，服从当前项目节点、资产与采用状态 |

专项负责自己的创作维度。普通润色不串行加载所有专项；一个明确的局部问题直接进入对应专项，不必绕回主入口。上游调用只携带必要原稿、素材职责、保留项和停止点。

## 写作与交付

先确认谁在什么空间、从何状态开始、发生何种变化、与谁交互、最后停在哪里。将景别与运镜放在能看清关键事件的位置；动作、对白、反应和声音按因果衔接。

默认交付一版可复制的中文正文。单镜可一段；多镜在需要时使用时间段；五模块适用于用户已采用该格式或复杂剧情，不要求所有任务套标题。模型参数、引用映射、未绑定状态和费用留在正文外。

用原稿与参考回对身份、空间、动作结果、声音和时长；没有看过实际成片时只称文字已检查。写作完成不自动触发上传、生成或发布。

旧名称通过兼容入口转到正式名称；需要解释历史规则包或旧调用时读[旧名映射](references/legacy-names.json)，不把发布包标识当作当前正式Skill名。

## 可选工作台

只有用户要求记录、从工作台排队任务续接，或当前项目已选用工作台时，才读取[可选工作台协议](references/studio.md)，沿同一 task/run 保存进度与候选。普通创作、采集与字幕直接在当前任务交付；工作台未配置不阻塞这些工作，也不替代原项目状态。
