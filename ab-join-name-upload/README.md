# 接B · 命名 · 上传清单（Codex Skill）

做完 A 段后，让 Codex 自动：从选B台挑 3 段合适的 B → 下载并校验 → FFmpeg 接片 → 技术核查 → 按团队命名规则命名 → 生成后台上传清单。**只在本机处理文件，不登录、不上传**；上传由本人在自己的后台账号完成，之后可把素材 ID 回填到本机台账。

> 本目录是公开源码，**不含团队配置**（人员代号表、后台字段可选项、选B台地址）。团队配置由负责人单独发放，用 `import-config` 导入。请勿把团队配置提交到本仓库。

## 安装（Mac）

需要：Codex（本人账号）、Python 3.9+、FFmpeg。

```bash
git clone https://github.com/WangLaoer02/paid-acquisition-pipeline-public.git
```

```bash
cd paid-acquisition-pipeline-public/ab-join-name-upload
```

然后双击 `双击安装.command`（或运行 `bash install.sh`）。把负责人发的 `团队配置*.zip` 放在“下载”文件夹里，双击安装会自动导入；也可以手动导入：

```bash
python3 ~/.codex/skills/ab-join-name-upload/scripts/abtool.py import-config --from ~/Downloads/团队配置.zip
```

以后更新：在仓库目录 `git pull`，再双击安装一次（已有配置会保留，变更前自动备份）。

也可以直接让 Codex 安装：

```text
从 https://github.com/WangLaoer02/paid-acquisition-pipeline-public 拉取 ab-join-name-upload，运行里面的 install.sh 安装技能，再用 import-config 导入我“下载”文件夹里的团队配置 zip，最后跑 doctor 告诉我结果。
```

## 买量工作台

安装会在本人电脑上建一个工作台（默认 `~/买量工作台`），所有产物都放在里面，按节点分层：

```text
~/买量工作台/
├── AGENTS.md / 开始使用.md / 工作台.json   ← 给 Agent 的规则、给人的一页说明、路径登记
├── 程序/  源码（git clone）、skills、tools（买量管线隔离安装）
├── 管线/  买量管线工作区（tools/public_release.py init --workspace 生成）
├── 配置/  团队配置（import-config 导入，不进仓库）
├── 台账/上传台账.csv
├── B段缓存/
├── 每日/YYMMDD/ 01_A段 · 02_接片 · 03_待上传 · 04_已上传 · 作废
└── 日志/
```

桌面上的「今日待上传」是指向当天 `03_待上传/` 的快捷方式；「买量看板.html」打开工作台的 `看板.html`，一眼看到今天进行到哪一步、每条素材的状态和还没回填素材 ID 的条目（`workspace board` 刷新，`run`／`record` 后自动刷新）。命令：`workspace init`（建立／补齐，可重复运行，不覆盖改过的 `AGENTS.md`）、`workspace today`、`workspace status`、`workspace migrate`（把旧版 `~/.ab-join-name-upload` 和 `桌面/待上传` 搬进来；内容核对一致才移走原件，同名不同内容的不搬）。

## 使用

见 [同事使用说明](同事使用说明.md)。核心命令：

| 命令 | 作用 |
|---|---|
| `run` | 一条命令：自动选 B → 下载校验 → 接片 → 核查 → 按连续序号命名出清单 |
| `record` | 上传后回填素材 ID 到本机台账 |
| `import-config` / `set-library` | 导入团队配置 / 更新选B台地址 |
| `doctor` / `ledger` | 环境检查 / 查看本机台账 |
| `workspace init/today/status/migrate/board` | 建立工作台 / 今天的目录 / 状态 / 搬入旧版数据 / 刷新看板 |

## 测试

```bash
cd skill/ab-join-name-upload && python3 -m unittest discover -s tests
```

测试使用 `tests/fixtures/team-config` 里的虚构配置，不访问任何真实服务。
