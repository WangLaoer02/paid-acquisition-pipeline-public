# 买量管线（公开源码候选）

从参考拆解、创意预演、角色物料、完整剧本与提示词，到生成、Premiere 剪辑、接 B、验收与上传的 24 节点工作流。保留运行脚本、节点合同、规则、渐进安装器、空模板和六卡说明网页。它需要 Agent 阅读和执行合同，不是一键自动成片程序。

**本版不代表作者的正式生产发布。** 不含作者项目、私有 Git 历史、媒体、账号、项目表或消费授权。离线准备可以直接运行；正式制作需要接收人的飞书规则源、项目 Sheet、服务账号和本机软件。项目自有代码采用 MIT，第三方许可分别保留，见 [LICENSE.md](LICENSE.md) 与 [第三方声明](THIRD_PARTY_NOTICES.md)。

拟发布仓库：`WangLaoer02/paid-acquisition-pipeline-public`（本候选尚未上传）。发布完成后从该仓库克隆：

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

## 按需安装

源码树 `skills/` 已包含规则阅读所需内容。要让 Agent 宿主发现 Skill，可安装到自己选择的目录，保留已有同名手改：

```sh
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools install --phase 0
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools install --phase 1
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools install --phase 2
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools install --phase 4 --backend dreamina
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools doctor --phase 4 --backend dreamina
```

阶段 0 为基础、1 为取片、2 为创作、4/5 为生成准备/执行、6/7 为后期。`install` 只装随包文件；外部依赖会明确列出，`doctor` 不把文件存在当作账号、原生软件或业务验收。媒体 Python 依赖可按需 `env-install --profile media`；商业软件与官方 CLI 见 [依赖来源](docs/dependencies.md)。

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
