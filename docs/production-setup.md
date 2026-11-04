# 接收人的正式接入

## 1. 配置与软件

初始化后编辑 `receiver.local.json`：`writer_host` 填运行时 `socket.gethostname()` 的真实结果；`rules_center` 填接收人自有飞书 Docx ID；`feishu_origin` 为自己的 `https://…feishu.cn` 或 `https://…larksuite.com` 租户域；`account_label` 为本人账号说明。不要填访问凭据。`backend` 按当前任务指定为 dreamina 或 rongyao，CLI 通过本人既有登录管理权限。

运行 `python3 tools/public_release.py config-check --production`。此检查只验证配置形状，不会将账号标为登录成功。

## 2. 在自己的飞书中心发布规则

在自己的租户建立一个规则中心文档。上传本公开版规则或把主要入口指向本版源码；按所用飞书官方 Skill 操作。运行 `python3 tools/public_release.py release-marker` 生成当前源码和 Skill 的本地哈希。把输出中 `release_id`、`manifest_sha256`、`skills_manifest_sha256`、`receiver_config_sha256` 四个字段组成 JSON，并在该文档单独一段写入：

```text
WF_RELEASE_JSON={"release_id":"实际输出","manifest_sha256":"实际输出","skills_manifest_sha256":"实际输出","receiver_config_sha256":"实际输出"}
```

保留且仅保留一个标记；不复制示例字样作为真实哈希。这个步骤发布的是接收人自己的固定规则版本，不是作者团队生产版本。运行 `python3 scripts/workflow_rules.py check`，它重新读自己的线上文档、比对规则与 Skill 哈希。源码发生改变时先检查差异和回归再更新发布；不能用离线模式替代此检查。

当前发行源码与配置隔离：账号说明、主机、规则文档位置存在本地配置；安全相关配置另由线上 receiver_config_sha256 固定。修改这些配置不会让源码 verify 失败，但正式调用会要求重新审核并发布配置哈希；规则、工具与 Skill 仍需哈希一致。任何登录检查、账号核验、当前输入、费用票据及动作锁仍由实际调用入口执行。

## 3. 接入项目 Sheet

优先使用接收人已有适合本任务的表；没有时在自己的租户建立任务专用表。复制 `templates/console.example.json` 和 `templates/state_bindings.example.json` 到工作区以外的临时配置，填写真实 project_id、名称、spreadsheet_token、sheet_id、实际镜头数及单选节点单元格的身份锚点。

绑定文件参数是单个对象（从示例的 bindings 数组中取本项目对象）。运行：

```sh
python3 tools/bind_project.py --console /你的目录/console.json --binding /你的目录/binding.json
```

此命令只写本地新项目配置和绑定，拒绝覆盖已有项目。它不证明 Sheet 的身份或状态；之后必须实时读取：

```sh
python3 scripts/console_content.py check --project 你的项目ID
python3 scripts/workflow_node.py context --item 你的真实item_id
```

空 Sheet 需要建立导演稿模板时，可在已完成自己的发布/登录核验后使用 `python3 scripts/console_template.py init --project 你的项目ID`。它是实际云端写入动作，执行前确认该表确为本人要初始化的目标；内部保留已有非空内容、手改与写前/写后回读检查。模板默认 DIRECTOR-STORYBOARD-1，不把预填示例当真实剧情。

## 4. 即梦非付费准备与正式制作

`python3 tools/public_release.py dreamina-prepare` 只检查本机 CLI 可用性。配置本人登录后显式 `--live` 查询版本、schema、状态、视频模型目录；查询结果的哈希用于诊断，不输出账号响应原文。请在本人服务内实际核对身份、授权、型号与规格。

正式生成必须沿 A09 当前完整稿、真实引用、声音/字幕/BGM、当前报价和预算、版本/上传范围组成第二停点，再由当前适配器检查并提交。默认模型与实际规格以实时目录为准。服务未提供的命令、模型、报价或权限不得虚构。受理结果未知时沿原 task 回查，不重新生成。A段由 Premiere 原生导出，最终对应分镜与完整音画一同验收。

当前公开候选未拿接收人账号做线上发布或生成验收；不承诺任意官方 CLI 版本即插即用。荣耀企业后端需管理员定制端点并重新构建固定发布，缺少企业服务权限时该分支不可用；不阻止离线创作与独立即梦准备。

## 企业后端端点适配

公开源码保留企业适配器，但所有原私有主机改为占位域。具备服务权限的接收人可在 `receiver.local.json` 的 `backend_hosts` 填完整的“占位主机名 → 本企业实际主机名”映射，然后导出到新的隔离工作区：

```sh
python3 tools/configure_backend.py --config receiver.local.json --workspace ../enterprise-pipeline --release-id YOURTEAM20261104.1
```

缺项会列出需要配置的占位主机名，输入中不允许 URL、凭据或不合法主机名。该命令仅复制并重建源码哈希，不登录、不调用后端、不发布；新版本须经过本企业接口实测和审核后在自己的规则中心更新标记。上传需求人/AI来源配置在 `workflow/maintenance/upload-acceptance/config/requester-ai-rules.json`，公开版为未配置状态；按自己的真实后台选项填写，再用 `tools/rebuild_release.py --release-id 新版本` 重建并验证。不得把作者历史员工、字段枚举或任务编号作为自己的配置。企业服务的协议差异可能需要进一步代码适配，当前未做接收人线上联调。

受管 Canvas 适配器 `scripts/dreamina_workflow.py` 当前范围是个人账号、单输出、无引用的 t2v。它不创建画布或节点、不支持团队计费或带图引用，也不自动处理费用结算；需要这些模式时必须扩展并验证相应适配器。先用官方 CLI 在本人已授权范围内准备画布/节点和报价，把当前值填入 templates/dreamina-plan.example.json。模板中的 unknown/null/approved=false 不构成可提交计划。
