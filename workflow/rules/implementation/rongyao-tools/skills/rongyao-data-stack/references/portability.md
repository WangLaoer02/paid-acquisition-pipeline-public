# Codex 跨电脑迁移

## 能力组成

| 层级 | 随 Skill 迁移 | 目标电脑仍需提供 |
|---|---|---|
| 筛选与指标口径 | 是 | 无 |
| 素材归一与分析阈值 | 是 | 无 |
| 本地 CSV/JSON 分析 | 是 | Python 3.10+ |
| 荣耀后台实时抓取 | 部分 | 网络、后台权限、Chrome 登录态、可用的 AES 库或经审阅的外部助手 |
| 历史实时数据 | 否 | 目标电脑重新查询后台，或用户另行提供数据文件 |

迁移包不包含密码、Cookie、Token、Chrome Profile、运行状态、导出数据或本机路径。

## 源电脑打包

```bash
SKILLS_ROOT="${AGENTS_SKILLS:-${CODEX_HOME:-$HOME/.codex}/skills}"
STACK_DIR="$SKILLS_ROOT/rongyao-data-stack"
python3 "$STACK_DIR/scripts/preflight.py"
python3 "$STACK_DIR/scripts/package_bundle.py" --output-dir "$HOME/Downloads"
```

记录脚本输出的 SHA-256，传输后可用 `shasum -a 256 <archive>` 核对。

把包交给别人时，只需让目标电脑的 Codex 解压并完整读取包根目录 `START_HERE_FOR_CODEX.md`；该文件包含安全安装、登录处理、预检和任务路由，不依赖原会话上下文。

## 目标电脑安装

在临时目录检查压缩包 SHA-256 和 manifest.json；先用包内 scripts/install_bundle.py 预览安装，再传 --apply。显式指定 --target 和全新的 --backup-dir；已有目标需 --replace。目标与备份目录必须互不包含。升级故障会恢复旧目录；rollback --backup-dir 可预览恢复，加 --apply 后恢复旧版并保留被替换的新版本。

```bash
python3 skills/rongyao-data-stack/scripts/install_bundle.py install --archive candidate.tar.gz --target staging/skills --backup-dir backups/first
```

Windows PowerShell 默认目录为 `$HOME\.codex\skills`；如设置了 `CODEX_HOME`，则使用 `$env:CODEX_HOME\skills`。使用当前 Codex 可用的 Python 3.10+ 解释器运行 `preflight.py`，不要依赖 Windows Store 的空 `python`/`python3` 别名。

安装后新开 Codex 任务，避免旧任务继续使用安装前的 Skill 快照。

## 后台登录

已配置本机钥匙包时沿 已安装的`rongyao-keyring` Skill 自动恢复现有账号，不重复询问授权或要求回复“已登录”。普通上传直接转rongyao-operations最短路径，由提交命令核验登录。以下人工步骤仅用于未配置钥匙包的目标机器或实际交互挑战；复制源码不转移凭据。

1. 在 Chrome 打开 `http://power.houtai.backend.example.invalid/`。
2. 用户自己输入账号、密码或完成飞书授权。
3. 登录后打开荣耀后台数据页，确认能看到“新素材2.0”。
4. 新建会话或失效重登后回到 Codex 回复“已登录”；已有可用会话不必每次重述。
5. Codex 执行本次已授权只读查询验证，不额外添加重型冒烟，不保存密码或 Cookie。

默认HTTP入口不读取Chrome Profile；Chrome活动桥使用原专用隔离配置。只有明确选择旧磁盘direct分支时，`--chrome-profile` / `--profile`才指定其Profile，不能把它扩写为所有查询默认读取日常Default。

## Python 与 Chrome 登录态

本地 CSV/JSON 分析只需 Python 3.10+。复用 Chrome 的 AES 加密 Cookie 时，需要 `cryptography` 或 `pycryptodome` 之一；Codex Desktop 的内置 Python 可能已包含 `cryptography`。缺少时先告知用户用途并征得同意，再安装：

```bash
python3 -m pip install pycryptodome
```

实际维护优先使用隔离虚拟环境，不修改系统或Codex托管解释器。离线格式验证另需PyYAML；测试运行与版本说明见 `references/runtime-and-validation.md`。预检默认不访问Cookie库；只有用户确需旧磁盘兼容诊断才加 `--check-disk-cookie`。

内置助手支持 macOS Chrome 的 Keychain/AES-CBC，以及 Windows 的旧式 DPAPI 和 `v10`/`v11` AES-GCM。Chrome 127 起在 Windows 上逐步为 Cookie 启用 App-Bound Encryption（`v20`）；这类密文绑定 Chrome 应用身份，通用 Python 助手不应绕过。预检发现 `v20` 时，使用经审阅且能合法复用会话的外部后台助手，或由用户提供权限受限的临时 Cookie 文件；不要关闭或降低 Chrome 的安全策略。

临时 Cookie 文件不得进入 Skill、迁移包或对话输出。POSIX 系统上将文件权限限制为 `600`；Windows 上使用当前用户专属 ACL。

## 后台助手与分支

业务查询入口只按rongyao-dashboard-filter-finder执行。普通素材CSV助手实际选择为显式--cli-path、RONGYAO_WEEKLY_REPORT_CLI、本机已安装HTTP适配器、专用Chrome助手、原外部助手及内置兼容助手；以material_performance.py的resolve_weekly_report_cli为准，提交后不换通道重放。

本迁移包的四件套可携带Chrome桥，但不会自动携带HTTP认证服务和本机凭据。目标机缺HTTP时明确报告使用已有Chrome兼容能力；不能把复制源码说成已获得免短信登录。preflight的助手候选与环境检查不代替业务入口选择或受保护读取。

只有已选Chrome分支才读 [Chrome会话维护](chrome-session.md)。通用筛选与批量汇总由scripts/readonly_capture.py实现；auto复用专用活动会话，进程确实退出才恢复同一配置，连接状态未知时停止。磁盘Cookie仅在显式direct或no-auto-recover兼容分支使用。运行内页面配置和动态选项缓存最多64项，进程结束即失效。

## 不能承诺完全相同的部分

- 后台权限、账号可见项目和登录方式由外部系统决定。
- 后台筛选项、响应字段和控制值变化时，Skill 会停止并要求重新核验。
- 不同 Codex 模型可能产生不同文字，但确定性脚本、阈值和加权计算应保持一致。
- 实时数据随查询时间变化；相同日期也可能因后台归因回补而更新。
