---
name: rongyao-material-analysis
description: "荣耀后台素材与投放专项分析 Skill。解释 ROI、付费、消耗、优质/潜力/爆R/吸量和素材标签，并针对攻略、品宣、原生录屏、福利、小剧场输出可追溯的方向或单素材 findings。用于给周报综合层提供专家判断；不负责多源采集、老板周报结构、下周排产、黄色表格或飞书发布。"
---

# 荣耀素材专项分析

## 定位

只回答“素材数据说明了什么”。输入优先使用 `rongyao-material-performance` 的已校验结果，也可使用用户提供的结构化 CSV/JSON 或 evidence bundle。

本 Skill 不抓取后台、不写周报总览、不套《0706周报》结构、不发布飞书，也不代替独立的下周排产流程。

## 必读规则

每次完整读取：

1. `references/language-style.md`
2. `references/report-logic.md`
3. `references/metrics-glossary.md`
4. `references/judging-rules.md`
5. `references/evidence-boundaries.md`：事实/名称/视频/逐字稿/创作建议分层及全项目、无匹配、来源链接边界。

按需读取：

- 项目背景：`references/project-context.md`
- 分类或标签：`references/material-taxonomy.md`
- 表达示例：`references/examples.md`，只学表达，不继承历史结论
- 状态汇报：`references/status-report.md`

`references/weekly-report-formula.md` 是成品周报的兼容路由，只在用户要完整周报时读取；不再保存第二套周报模板。

## 输入门槛

按任务检查素材名、方向/标签、花费、ROI1、付费、2日倍率、命中类型、统计周期；涉及趋势时还要有连续上一期和新老素材口径。

调用方应传入 `rongyao-material-performance` 的 `summary.json` / 已校验 `analysis.json`，或结构等价的 evidence bundle。必须保留 `contract`、`data_quality.missing_required_columns`、`capture_validation` 和实际日期；若上游任一查询为 `missing/backend_unhealthy`，本 Skill 只能报告缺口，不得自行重抓后台或补0。

## 输出契约

结构化底稿 `analysis_findings` 包含：

- `evidence_type`：backend_metric / backend_label / material_name / source_video / transcript / user_input / generated_proposal；每项只用一种，混合判断拆项。
- `topic`：方向、标签或素材对象。
- `judgment`：结论。
- `support_fact_ids`：支持事实。
- `counterevidence_fact_ids`：反例或不一致事实。
- `boundary`：样本、周期、口径和不能外推之处。
- `next_test`：无验证建议时为 null；需要对照时说明固定、替换的实际变量与要验证的问题。
- `coverage`：实际项目、排除/失败项目、可见项目枚举状态、双日期边界、阈值及来源。

本周和新产日期以输入契约为准；`maturity.includes_recent_days=true` 时结论是阶段性观察，不能等同完整周。`material_range_source=legacy_default_unverified` 不是全历史，`new_material_window_covered=false` 不是新产全量。后台优质标签和按阈值判断的指标达标须分列，不能互换。

