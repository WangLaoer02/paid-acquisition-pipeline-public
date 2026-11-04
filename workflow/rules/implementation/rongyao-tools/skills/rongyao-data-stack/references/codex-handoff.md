# Codex：请从这里开始

这是一个只面向 **Codex** 的荣耀后台数据 Skill 迁移包，不要求 OpenClaw。请完整读取本文件后再执行安装。

## 任务目标

把包内五个 Skill 安装到当前用户的 Codex Skill 目录，使这台电脑获得：

- 荣耀后台筛选、标签、月度消耗、产出数量、素材编号和原创统计能力；
- 火影/忍界大战素材表现抓取、ROI、付费、2日回收、新老素材和方向聚合能力；
- 素材有效点、方向、代表案例和反例分析能力；
- 环境预检、荣耀钥匙包自动登录及无凭据迁移能力。

钥匙包当前的钥匙串执行器适用于macOS；查询四件套保留原跨平台能力。上传技能是本机已有依赖，不包含在这个数据迁移包内。

## 安全边界

- 本包声明为无凭据包，不含密码、Cookie、Token、Chrome Profile、后台导出数据或运行状态。
- 不要求用户把密码粘贴到对话中；密码只在已授权的本机凭据库和固定执行程序内使用，不写入本包。
- 不修改荣耀后台，不上传或发布数据，不使用浏览器逐页抓取。
- 通用抓取入口为 `rongyao-data-stack/scripts/readonly_capture.py`；高成本分页由脚本在后台查询会话内串行完成，不做浏览器 DOM 翻页。
- 安装第三方依赖、覆盖已有 Skill 或执行首次真实后台查询前，先告知用户。

## 第一步：检查包

确认根目录至少包含：

```text
START_HERE_FOR_CODEX.md
manifest.json
skills/rongyao-data-stack/
skills/rongyao-dashboard-filter-finder/
skills/rongyao-material-performance/
skills/rongyao-material-analysis/
skills/rongyao-keyring/
```

读取 `manifest.json`，确认：

- `format=rongyao-codex-skill-bundle-v2`；
- `credential_free=true`；
- `target_runtime=Codex`；
- 五个 Skill 均在清单中。

如果包结构或清单不完整，停止安装并告诉用户。

## 第二步：安全安装

目标目录：

```bash
TARGET_ROOT="${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}"
```

Windows PowerShell 默认使用 `$HOME\.codex\skills`；若设置了 `CODEX_HOME`，则使用 `$env:CODEX_HOME\skills`。

安装前逐个检查目标目录是否已经存在同名 Skill：

```text
rongyao-data-stack
rongyao-dashboard-filter-finder
rongyao-material-performance
rongyao-material-analysis
rongyao-keyring
```

如果存在，不直接覆盖；先比较版本和文件，向用户说明差异并确认保留、备份或替换。不存在时，把包内 `skills/<name>` 完整复制到 `$TARGET_ROOT/<name>`。

安装后新开一个 Codex 任务，使 Skill 清单重新加载。不要为此安装或配置 OpenClaw。

## 第三步：运行预检

```bash
TARGET_ROOT="${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}"
python3 "$TARGET_ROOT/rongyao-data-stack/scripts/preflight.py"
```

Windows 或 Codex Desktop 中 `python3` 不在 PATH 时，使用当前 Codex 可用的 Python 3.10+ 解释器。

解释结果：

- `analysis_ready=true`：可以分析已有 CSV/JSON。
- `capture_environment_ready=true`：抓取脚本、后台助手和本机登录入口存在，但登录态仍需真实查询验证。
- `login_verification_required=true`：正常安全提示，不代表安装失败。

预检默认不读取或复制Cookie库，未检查不能解释成登录失效。格式与离线回归依赖说明见 `rongyao-data-stack/references/runtime-and-validation.md`；用隔离环境补齐，不改系统Python。

若预检提示缺少 AES 库，先告知用户用途并取得同意，再安装 `pycryptodome` 或 `cryptography`：

```bash
python3 -m pip install pycryptodome
```

Windows Chrome 如使用 App-Bound Encryption（`v20`），内置 Python 助手不绕过该保护。使用经审阅的外部后台助手，或由用户提供权限受限的临时 Cookie 文件；不要降低 Chrome 安全策略。

## 第四步：处理登录

登录恢复统一按已安装的rongyao-keyring合同。查询按主查询Skill选定执行器内置认证；ensure-query仅用于Chrome分支独立诊断，不作HTTP前置。普通成片上传直接读rongyao-operations最短路径，由upload内部恢复登录，不先探测查询或IAB。本机现有用户已明确授权任务内登录，无需重复询问；仅在正常登录表单按需提交一次。验证码、系统权限或真实拒绝报告具体阻塞。新电脑复制源码不会获得凭据或登录态，只在该电脑获得初始化授权后才导入其现有账号。以下人工步骤只适用于未配置钥匙包的机器。

如果预检或查询提示没有 Chrome Cookie、登录态失效或需要授权：

1. 提醒用户在 Chrome 打开 `http://power.houtai.backend.example.invalid/`。
2. 让用户自行输入账号、密码或完成飞书授权。
3. 等待用户回复“已登录”。
4. 再继续原来的只读查询。

普通已有会话直接用用户已授权查询验证，不每次再要求口头确认，也不额外插入冒烟。专用会话断连或状态不明时不自动切换磁盘Cookie；只在确实不存在专用会话时才允许既有兼容入口。

未配置自动登录时由用户自行输入；配置钥匙包后使用固定执行器。始终不索取或打印密码，不把密码或 Cookie 写入 Skill。

## 第五步：按任务路由

| 用户请求 | 使用 Skill |
|---|---|
| 查筛选、标签、导出、月消耗、产出数、编号、原创数 | `rongyao-dashboard-filter-finder` |
| 查具体日期素材表现、ROI、付费、回收、角色、方向、新老素材 | `rongyao-material-performance` |
| 判断素材为什么有效、方向是否成功、找反例和适用边界 | `rongyao-material-analysis` |
| 迁移、打包、安装、环境检查 | `rongyao-data-stack` |
| 自动登录、会话及入口核验 | `rongyao-keyring` |

涉及素材表现结论时，先用 `rongyao-material-performance` 取数，再用 `rongyao-material-analysis` 判断；禁止把推测写成事实。

参数完整时直接运行目标 Skill 的确定性命令，不执行目录扫描、`--help`、源码搜索、重复状态查询或浏览器逐页。详细命令见 `skills/rongyao-data-stack/START_HERE.md`。

自然语言日期和抓数习惯见 `rongyao-data-stack/references/capture-habits.md`；能确定“本周”日期、火影项目和输出路径时不要求用户逐项填写。`run --dry-run` 是纯离线规划，不代表已经查询或认证。

## 后台固定口径

- 火影=`忍界大战(193)`，`gid=193`。
- 日期汇总=`区间汇总2`，后台值 `date_group=tenyear`。
- 素材维度=`group=mid`。
- 类型=`视频`，过滤数据=`是`。
- ROI1按花费加权；观察线500元；ROI1参考9%；2日倍率参考1.9。
- 项目总量优先读取后台总计行；明细与总计有差额时报告差额，不猜原因。

完整细则以每个 Skill 的 `SKILL.md` 和 `references/` 为准，本入口不覆盖业务 Skill 的最新规则。

## 安装完成的判断

满足以下条件才可以告诉用户“已可使用”：

1. 五个 Skill 文件完整；
2. 预检 `analysis_ready=true`；
3. 需要实时查询时，本次实际HTTP或Chrome入口的受保护读取和后台权限已经验证；
4. 一次只读查询的项目、日期、行数和必需字段校验通过。

不同Codex模型可能产生不同文字，但确定性脚本、筛选口径和加权计算应保持一致；实时数据可能因后台归因回补而变化。

## 单一源码与可选登录依赖

四个数据Skill为核心套件；钥匙包仅在本次选定根目录实际存在且通过白名单检查时随包携带。manifest的optional_dependencies_not_bundled明确缺项；未包含钥匙包时，不宣称自动登录可用，沿目标设备已有授权入口处理。安装目录可引用同一源码目录；打包只复制白名单普通文件，不携带运行状态或凭据。
