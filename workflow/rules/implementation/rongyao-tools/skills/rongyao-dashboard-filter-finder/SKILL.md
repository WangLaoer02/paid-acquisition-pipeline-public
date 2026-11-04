---
name: rongyao-dashboard-filter-finder
description: "荣耀新素材2.0统一入口：按项目、双日期和筛选查询或导出数据，并按需分析火影/忍界大战素材消耗、ROI、角色与方向。导出与分析共用同一抓取流程；rongyao-material-performance保留为兼容名称。"
---

# 荣耀新素材2.0：查询、导出与分析

本Skill是统一入口。`rongyao-material-performance`是同一套流程的兼容名称和分析脚本所在目录，不独立维护查询、认证或导出规则。既有脚本路径保留，避免破坏调用方。

## 按目的选择模式

| 用户目的 | 执行 |
|---|---|
| 识别字段、筛选或只制定计划 | 读取字段地图；普通素材查询用下面的 `--dry-run`，不访问后台 |
| 导出火影素材表现数据 | 共用脚本的 `export`，交付CSV和校验回执，不自动生成分析 |
| 查询火影素材表现、消耗、ROI或方向 | 同一脚本的 `run`，抓取一次后本地分析 |
| 分析已有CSV | 同一脚本的 `analyze`，不重新抓取 |
| 月度总计、跨项目、素材编号、原创素材或自定义筛选 | [专项汇总](references/aggregate-queries.md)与[字段地图](references/export-and-filter-map.md)，保持原口径和已有兼容入口 |

只有用户要求对比才增加对比期。一次任务同时要导出和分析时只运行一次 `run`，交付该次CSV和分析；已有同口径CSV则直接 `analyze`。不要依次执行 `export` 和 `run` 重查同一份数据。

## 共用数据与认证契约

- 日期、项目、字段、缓存、查询次数与文件完整性统一由[查询契约](../rongyao-material-performance/references/query-contract.md)定义，执行前读取。日期来源和相对时间使用[抓数习惯](../rongyao-data-stack/references/capture-habits.md)，这里不另设默认范围。用户没有日期意图时不默认最近周期。
- 火影=忍界大战 `gid=193`。普通素材模式固定 `date_group=tenyear`、`group=mid`、视频、新注册、过滤数据=是。投放日期与素材产出日期分别核验，不能相互代替。新素材2.0投放样本不代表完整生产台账。
- 普通素材的 `export` 与 `run` 共用 `resolve_weekly_report_cli`、`capture_one_cached` 和 `capture_one`：显式 `--cli-path` > `RONGYAO_WEEKLY_REPORT_CLI` > 本机已安装HTTP适配器 > 原Chrome活动会话入口 > 原兼容助手。HTTP适配器目前仅支持 `gid=193/tenyear/mid`；其他项目、维度、额外列或浏览器专用参数需在提交前选用支持它们的原入口，不静默丢弃筛选。
- HTTP入口复用本机服务或本机Keychain保存会话；实际失效后按该机器原认证路径恢复。`rongyao-keyring`（按当前环境的已安装Skill目录按名称读取，不从本文件物理相邻目录推断路径）定义机器差异。MacBook原自动短信与Mac mini原人工/群备用分别保留，不因统一Skill改变。只有未安装HTTP适配器或用户明确选择时使用Chrome兼容路径，其会话规则见[活动Chrome](../rongyao-material-performance/references/active-chrome-session.md)。
- 不另发指标冒烟。每个区间一次提交；分页复用该次 `rand`。提交后的超时、504、认证拒绝或受理未知立即停止，不重试、不换通道重放。高成本素材编号强制单实例和串行分页。
- 短期缓存须精确匹配项目、双日期、数据维度、SHA和TTL；输出披露命中及来源。要求“最新/实时”时用 `--cache refresh`，不把缓存说成新查询。
- 不以登录状态或生成文件本身证明成功；核验返回项目、双日期、必需字段与文件。缺失值保留null，后台总计与明细汇总及差额分别报告。

## 普通素材统一执行入口

以下命令在本Skill目录执行；`this-week`只适用于用户确实指定本周的情况。日期明确时用 `--date-range`，素材范围用 `--material-range`；参数规则见查询契约。

```sh
python3 ../rongyao-material-performance/scripts/material_performance.py export --period this-week --gid 193 --dry-run
python3 ../rongyao-material-performance/scripts/material_performance.py export --period this-week --gid 193
python3 ../rongyao-material-performance/scripts/material_performance.py run --period this-week --gid 193
python3 ../rongyao-material-performance/scripts/material_performance.py analyze --current <已核验CSV路径>
```

`export`和`run`使用相同日期解析、身份核验、缓存与抓取代码。导出输出 `current.csv`、明确对比时的 `previous.csv` 及 `export.json`，回执包含双日期、行列数、编码、SHA、缓存/查询证据；`run`在同份数据上追加分析。输出目录唯一且不覆盖已有文件。

需要分析时读取[分析模式](../rongyao-material-performance/references/performance-analysis.md)与[判断契约](../rongyao-material-performance/references/judgment-contract.md)。普通数据问题只回答所需结论，不自动制作周报、图表或发布飞书。视频链接和关键帧仍走[视频快取](../rongyao-data-stack/references/video-chatgpt.md)。

## 筛选、交付与边界

- 数据身份识别读[数据身份](references/data-identification.md)；筛选、额外列或后台原生文件导出读[字段地图](references/export-and-filter-map.md)；汇总结果读[输出契约](references/output-contract.md)。原生下载格式以真实响应为准，不与结构化CSV混称。
- 普通读取/分析允许所需CSV传输；仅用户明确要求导出/下载时交付导出文件。导出和分析授权不包含上传、分享、修改后台、保存默认值或发布报告。
- 同时列出实际项目、日期、未覆盖范围、失败项和差额。证据边界见[证据规则](../rongyao-material-analysis/references/evidence-boundaries.md)：指标事实、标签、名称推断、视频观察和建议分开；未看视频不编造镜头、台词或因果。
