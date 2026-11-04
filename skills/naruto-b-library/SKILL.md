---
name: naruto-b-library
description: 维护火影可复用B段素材库；用户给视频时增量截取、保留原编号和原声、记录第二设计师与主推角色，并在选B与接B时查询已有资产。
---

# 火影 B 段库

资产配置见 [library-location.json](references/library-location.json)。实体素材与来源只维护该配置指向的库；节点状态和项目采用仍从现有飞书项目 Sheet 读取。素材库由接收人独立配置，未配置时不得推断有可用资产。

## 用户提供视频时追加

先查现有 `index.json`；仅处理接收人明确提供或授权的素材。保留原片，按实际画面确定游戏 B 起点，连续音轨另行核对；混合片提取 B，纯 B 保留完整内容。跨 IP、标题与实际主体不符的片段保留排除原因。

来源编号与 B 原创编号分列：从组合片截取只能确认该组合片编号，查不到更早 B 原件时原创编号为 null。后台登记角色与实际 B 主推角色分列，按画面识别后者。源成片的后台第二设计师和本次复用应填的第二设计师也分别保存；后台“暂无”不等于复用时无需归属。导师和实习生归属只采用已核实证据，缺项保留 null，用户随后提供时补齐。

将实际输入写入 JSON，交给配置中的 `maintenance_script add --record 文件路径`。输入必需 `source_path`（真实原片路径），其余字段按已有记录保存：`source_code`、`source_name`、`original_b_code`、`title`、`second_designer`、`source_second_designer`、`source_designer`、`main_role`、`backend_roles`、`source_start`、`source_end`、`source_ref`、归属和切点证据。`full_audio_reviewed` 只有实际完整听过才能设 true。脚本复制原件、截取带原声副本，核对媒体流、时长、完整解码及 SHA，按原片 SHA＋区间去重并更新预览和清单；冲突保留原件停止覆盖。

`stats` 返回库内实体片段数、角色分布及缺项数。`validate` 核验原片、B 副本和预览。交付提供 `index.html` 与 `B段清单.csv`，说明第二设计师、原创编号和听审的实际缺项。已入库不自动等于可接或用户采用。

用户随后补充归属或角色证据时，用 `amend --id 库ID --record 补充JSON` 更新元信息，并填写 `credit_evidence`；脚本保留修改前记录且不重做视频。切点或素材内容改变则新增版本，不把元信息补齐当成重新截取。

## 接入买量工作流

在买量管线执行生产前，已有真实item时直接沿该仓库 `python3 scripts/workflow_node.py context --item <真实ID>` 读取当前飞书节点合同，对象未知才先list，不从本 Skill 复制或发布规则。

- LIBRARY01—03：本库提供原片、来源、剪辑区间、原声和技术回执；验收与 LIBRARY04 可接状态仍依当前合同和唯一 Sheet。
- B01：优先在本库按主推角色、卖点、第二设计师或编号选择，锁定库 ID、源 SHA、B 副本 SHA 和真实区间。归属未知时可审看片段，正式归属保持待核。
- B02—B04：按当前合同将本库实体 B 交给 FFmpeg 接片；A 沿 PR 原生导出，接点、混音、完整听审及采用逐项核验。

现有 `rongyao-video-upload` 已引用本库入口。公开版无历史已验证预设；接收人核验后才能登记。需要正式上传计划时，沿该 Skill 的 `b_source` 协议，在第二设计师名称和值、角色选项和成品核查实际齐备后提供精确字段。

本地资产整理不写在线项目正文或推进节点。飞书回填继续使用当前发布的 `console_content check → patch/image`，在已发布 writer_host 上执行；缺少库专用写入槽时保留回填候选，不能直写绕过。后续提供的视频逐条追加同一库，不新建平行状态表。

