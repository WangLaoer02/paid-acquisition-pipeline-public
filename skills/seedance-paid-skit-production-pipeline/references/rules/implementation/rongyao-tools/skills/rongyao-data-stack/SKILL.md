---
name: rongyao-data-stack
description: "Maintain the 荣耀后台 Skill stack, reuse login, fetch 新素材2.0 video links and sampled frames, and expose read-only MCP tools for ordinary ChatGPT. Use when the user asks to organize or transfer 荣耀 Skills to another computer, verify whether another Codex can reproduce data capture and material analysis, diagnose missing helper/login/dependencies, or build a credential-free portable bundle. Do not use for ordinary data queries when a narrower 荣耀 Skill already applies."
---

# 荣耀数据 Skill 套件

## 登录与执行路由

登录恢复唯一依据是已安装的 `rongyao-keyring` Skill，按当前环境Skill目录按名称读取；不从本文件的物理相邻目录推断路径。普通任务直接运行对应执行器，不预跑ensure-query或上传/IAB探测。

普通新素材2.0查询、导出与分析由 `rongyao-dashboard-filter-finder` 统一选入口，本机支持的素材CSV默认HTTP；本Skill的 `readonly_capture.py` 是跨项目/额外维度Chrome查询桥，`fast_video.py` 是视频/MCP桥。成片上传直接转已安装的 `rongyao-http-upload`，operations保留计划与账本。AI仍用独立ryai和ensure-ai。各分支的会话分别验证，提交未知沿原入口回查。

## 结果可信边界

范围必须列出实际项目、排除和失败项目、可见项目枚举状态及双日期边界；当前活跃项目不代表所有历史项目。名称无匹配写“本次口径未检出”。指标事实、后台标签、名称推断、视频观察、逐字稿、用户陈述和创作建议分别标 evidence_type；内容未核验不推断具体台词镜头。完整规则见 `rongyao-material-analysis/references/evidence-boundaries.md`。

缺失指标保留 null，后台原始倍率与推导倍率分列；ROI1为0时倍率未定义。报告后台总计、明细汇总及差额，原因未知就保留未知。原始 demand_url 不改写；提取、访问和播放状态独立记录。临时比较阈值注明来源，不当业务标准。

实时查询必须传递已解析的素材产出边界并记录来源，不沿用历史截止日期。默认习惯、兼容窗口及何时需要澄清见 `references/capture-habits.md`。查询提交后不自动重试（retries=0），缺失项不补0。专用会话断连或状态不明时停止，不跨通道重放。

普通已授权业务查询可以验证现有登录态，不要求每次重新口头确认，也不额外插入冒烟查询。只有专门运行 `scripts/live_regression.py` 时才使用其手动登录确认门控；它是可选安装验收，不是每次抓数的前置步骤。


把三层能力保持分离：

- `rongyao-dashboard-filter-finder`：筛选、月度指标、产出数量、编号与导出契约。
- `rongyao-material-performance`：结构化素材表现抓取、校验、归一和聚合。
- `rongyao-material-analysis`：ROI、付费、回收、方向和代表素材判断。

本 Skill 负责迁移、环境检查、会话复用，以及视频快取和 ChatGPT 接入；业务指标判断仍交给上述业务 Skill。

## 视频链接、内容与普通 ChatGPT

用户需要新素材2.0视频直链、关键帧内容或ChatGPT接入时，先读 `references/video-chatgpt.md`，使用 `scripts/fast_video.py` 和 `scripts/video_mcp.py`。优先复用专用会话；本机可选配置凭据只在正常登录表单提交一次，遇验证码或拒绝即停。已有查询失败不自动重放。

## 专用Chrome汇总查询桥

仅在主查询Skill已选定跨项目、额外维度或素材编号的Chrome分支时使用下列桥。普通素材CSV仍由主查询Skill选择HTTP，不为读取本Skill额外切换传输。该分支示例：

```powershell
python scripts/readonly_capture.py query `
  --date-range 2026/08/01-2026/08/07 `
  --material-range 2023/01/01-2026/08/05 `
  --gid 193 --group mid --role 凯
```

默认传输为：复用专用 Chrome 活动会话；如该进程已退出，自动使用同一凭据隔离配置重启，再直连查询。旧磁盘 Cookie 只作显式兼容路径（`--transport direct` 或 `--no-auto-recover`）。已知 Chrome 进程仍在但 DevTools 断连时停止，不启动第二个会话；查询已发出后失败也不重放。`batch --request-file` 在一次页面初始化内复用页面配置、动态 `category/pkid/pcid`，元数据缓存只存在于本次进程、最多64项。业务结果的短期精确缓存由 `rongyao-material-performance` 管理，只保存无凭据CSV和口径元数据，不进入迁移包或Git。

`group=material_serial_number` 自动进入高成本模式：只能单请求、并发1、首次提交一次，后续页复用 `rand`。普通汇总批量最多并发6；失败项保持 `missing`，不得补0。

## Codex 迁移流程

1. 首次安装/修复时运行预检，区分本地分析、传输环境、已认证访问；普通业务查询不重复整个预检。
2. 生成无凭据压缩包；禁止打包 Cookie、密码、Token、会话、后台导出数据或运行状态。
3. 把压缩包交给目标电脑的 Codex，并让它先完整读取包根目录 `START_HERE_FOR_CODEX.md`。
4. 在目标电脑解压到 Codex Skill 目录（默认 `${CODEX_HOME:-$HOME/.codex}/skills`，仍兼容 `AGENTS_SKILLS`）；目标路径已有同名 Skill 时先比较并征得用户确认，不直接覆盖。
5. 重启或新开 Codex 任务，使 Skill 清单重新加载。
6. 首次部署才预检环境；已配置本机钥匙包时沿现有账号授权正常自动登录，不重复询问或要求回复“已登录”。缺配置先查access目录和现有环境；新机器的初始化与验证码/系统许可分别报告，不能把未检查当掉线。
7. 环境就绪后执行本次已授权业务，由执行器验证入口。上传转rongyao-operations最短路径；只读查询不额外冒烟。不得索取密码。

详细安装与能力边界见 `references/portability.md`。

## 预检

```bash
SKILLS_ROOT="${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}"
STACK_DIR="$SKILLS_ROOT/rongyao-data-stack"
python3 "$STACK_DIR/scripts/preflight.py"
```

Windows 或 Codex Desktop 中 `python3` 不在 PATH 时，使用当前 Codex 可用的 Python 3.10+ 解释器执行同一脚本。

预检默认不读取或复制Chrome Cookie库；只有明确诊断旧磁盘兼容入口时才传 `--check-disk-cookie`。不把“未检查”写成“未登录”。

预检输出三种状态：

- `analysis_ready`：Skill、规则和本地分析脚本完整，可分析已有 CSV/JSON。
- `capture_environment_ready`：后台助手、Python 依赖和当前平台的 Chrome/Cookie 入口兼容；不等于登录态已验证。
- `login_verification_required`：访问尚未验证，不等于未登录；已配置钥匙包时由本次执行器按需恢复并验证，未配置时才进入对应初始化/人工分支。

缺少依赖或做回归时读取 `references/runtime-and-validation.md`。本机维护版见 `references/bundle-files.json` 的版本；修改后必须更新白名单并验证包，不声称是未改动的上游提交。

## 无凭据打包

```bash
SKILLS_ROOT="${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}"
STACK_DIR="$SKILLS_ROOT/rongyao-data-stack"
python3 "$STACK_DIR/scripts/package_bundle.py" --output-dir "$HOME/Downloads"
```

打包固定包含本 Skill 和三套业务 Skill。脚本使用白名单文件、排除缓存，并在写包前扫描常见密钥格式。
包根目录固定包含 `START_HERE_FOR_CODEX.md` 和带入口、安装布局、Skill清单、安全声明的 `manifest.json`。

## Chrome分支维护

仅在已选Chrome分支或排查专用会话时读取 [Chrome会话维护](references/chrome-session.md)。本机已配置钥匙包时沿固定助手自动恢复；该参考中的人工初始化仅适用于未配置机器。HTTP服务、AI会话和IAB不以此页面登录状态代替。

## 能力结论规则

- 只复制 Skill：可获得相同口径、脚本和分析方法，但不能自动获得账号权限或登录态。
- Skill 完整、依赖满足、后台可访问且登录成功：可获得等价的数据查找和分析流程。
- 模型版本、后台字段或数据更新时间不同，最终措辞和实时数字可能变化；不得承诺逐字或逐数永久一致。
