# 买量管线（公开源码）

从参考拆解、创意预演、角色物料、完整剧本与提示词，到生成、Premiere 剪辑、接 B、验收与上传的 24 节点工作流。保留运行脚本、节点合同、规则、渐进安装器、空模板和六卡说明网页。它需要 Agent 阅读和执行合同，不是一键自动成片程序。

**本版不代表作者的正式生产发布。** 不含作者项目、私有 Git 历史、媒体、账号、项目表或消费授权。离线准备可以直接运行；正式制作需要接收人的飞书规则源、项目 Sheet、服务账号和本机软件。项目自有代码采用 MIT，第三方许可分别保留，见 [LICENSE.md](LICENSE.md) 与 [第三方声明](THIRD_PARTY_NOTICES.md)。

公开仓库已上线：[WangLaoer02/paid-acquisition-pipeline-public](https://github.com/WangLaoer02/paid-acquisition-pipeline-public)。本源码版本：`PUBLIC20261104.2`。克隆公开源码：

```sh
git clone https://github.com/WangLaoer02/paid-acquisition-pipeline-public.git
cd paid-acquisition-pipeline-public
```

## 最短开始

需要 Python 3.10+；代码中的主机锁与原生桥主要面向 macOS，其他系统尚未验收。

```sh
python3 tools/public_release.py verify
python3 tools/public_release.py init --workspace ../my-pipeline
cd ../my-pipeline
python3 scripts/workflow_node.py list
python3 scripts/workflow_node.py context --node A01 --condition new-project --offline-preparation
python3 scripts/workflow_node.py context --node A02 --offline-preparation
python3 scripts/workflow_node.py context --node A03 --offline-preparation
```

`init` 只接受不存在的新目录，复制公开清单内文件，创建空项目状态与 `receiver.local.json`，不安装全局 Skill、不登录、不写云端。离线读取不会推进项目、生成、消费或上传。

打开 `00_开始使用.html` 查看六卡、浮窗与二级节点导航；也可运行 `python3 -m http.server 8765` 后在本机浏览器打开该文件。本仓库未配置 GitHub Pages，不提供已上线网页承诺。

## 安装与依赖汇总

Python 3.10+ 和 Git 由目标机器提供。先确认 Agent 的 Skill 搜索目录；以下相邻目录用于隔离安装，避免覆盖现有版本。只需要当前阶段时把 `--phases` 改为对应阶段（例如 `0`）；完整范围用 `all`。

```sh
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools setup --phases 0,1,2,4,5,6,7 --backend dreamina --with-official-skills
```

`setup` 汇总每阶段 install、doctor 和外装获取结果。退出 **2** 代表未完成：逐项读取 `missing`、`steps` 中的失败原因，处理后使用同一命令和目录重试。退出 **0** 只表示所选阶段的文件校验与本机软件基础探测通过；`runtime_ready`、`business_ready` 始终单独保持未验收。不能把“37个随包 Skill 已复制”、外装缺失或 doctor 2 写成全部安装完成。

该命令仅按需从官方固定来源取得飞书四 Skill，保留 MIT 许可。**默认国内即梦没有本轮核实的公开自动获取来源，仍明确列缺项**。现有其他版本、空 SKILL.md 或手改均不冒充完整官方安装；保留原件，在新的隔离目录比较，再由维护者核对兼容性。国际 Dreamina 是显式可选路线，见 [依赖来源与补齐命令](docs/dependencies.md)。

常见缺项可逐项补齐后重跑 setup：

```sh
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools tool-install-feishu
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools env-install --profile media
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools env-install --profile premiere
```

官方 CLI、FFmpeg、Premiere、宿主图像工具、模型和账号分别检查；安装器不登录、不下载模型、不生成、不写项目表、不上传。单独运行 `install --phase N` 只复制文件，外装未验证时也退出 2；`doctor --phase N` 只读。安装器不修改系统 PATH，调用工具时使用输出路径或在当前终端临时加入 `my-tools/bin`、`my-tools/npm/node_modules/.bin`。

给 Codex 的接入指令：

```text
读取公开仓库 README，核对当前版本和目录。用 setup 安装我需要的阶段及合法官方依赖；保留已有文件和登录配置。完整报告 installation_complete、files_ready、software_probe_passed、runtime_ready、business_ready，以及每项缺失/冲突/恢复步骤；任一外装失败或 doctor 2 都不能汇报安装完成。国内即梦不自动切国际版。只做本机安装和只读检查，不登录新账号、生成、付费、写项目表或上传。
```

## 配置自己的正式工作区

编辑 `receiver.local.json`，填写本人主机名、飞书规则文档 ID、租户 origin、账号说明和生成后端。账号说明只用于识别，不证明登录；密码/Token/Cookie 只保留在服务官方登录配置中。再按 [正式接入](docs/production-setup.md) 配置自己的规则源与项目 Sheet。

```sh
python3 tools/public_release.py config-check --production
python3 tools/public_release.py dreamina-prepare
```

第二条仅检查 CLI 是否可用。显式加 `--live` 才会执行版本、schema、登录状态与模型目录的只读查询；不创建画布、不生成、不接受报价。生成前仍需实际账号/权限、当前报价和第二停点授权。当前公开候选尚未使用接收人账号完成真实生成。

## 已覆盖与限制

本轮验证结果见 [验证范围](docs/validation.md)。离线读取与安装成功不表示飞书上线、账号授权或生成成功。Dreamina 官方二进制/Skill、飞书官方 Skill、Premiere、FFmpeg 由接收人安装。企业荣耀适配代码保留，但公司私有地址已移除，默认不能连接；需企业管理员核验本人权限、配置合法服务端点并重新发布自己的固定版本。未提供公共荣耀服务。

最终交付须实测全片时长、连续音画与逐镜分镜对应；真实生成、Premiere 原生导出和业务上传在当前无接收人账号的验证中均未执行。
