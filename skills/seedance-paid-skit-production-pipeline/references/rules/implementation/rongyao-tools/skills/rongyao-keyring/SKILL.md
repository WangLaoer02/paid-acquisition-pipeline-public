---
name: rongyao-keyring
description: "荣耀后台钥匙包：在荣耀数据查询、视频检索和上传任务中复用本机现有账号，自动检查并恢复登录，不重复询问登录授权。用于登录失效、入口核验及现有荣耀业务技能的接入；业务查询和视频上传仍由对应技能执行。"
---

# 荣耀钥匙包

## 唯一登录合同与业务入口

本文件是本机荣耀账号复用、机器差异、撤销与登录恢复的唯一决策入口。其他Skill只维护各自业务及协议实现，不另选默认认证方式。“免登录”指复用有效会话或从本机Keychain恢复，不代表绕过认证或永久有效。

| 本次任务 | 唯一执行路径 | 认证范围 |
| --- | --- | --- |
| 火影新素材2.0普通素材查询、CSV导出、分析 | 已安装的 `rongyao-dashboard-filter-finder` → `rongyao-material-performance/scripts/material_performance.py` | 显式CLI/环境配置优先；本机默认 `rongyao-http-readonly/scripts/market_export_cli.py`。执行器内恢复，不预跑ensure-query。 |
| 视频列表、分类117产出及受控分页 | 已安装的 `rongyao-http-readonly/scripts/rongyao_http.py` 的 video-list/query | readonly HTTP服务；首页结果与完整分页分别验收。 |
| 月度跨项目、编号、额外维度 | dashboard-filter-finder 的 aggregate-queries参考 → data-stack 的 readonly_capture.py | 当前实现是专用Chrome，提交前按能力选定，不把HTTP失败当切换理由。 |
| 新素材2.0视频搜索、直链、关键帧及MCP | data-stack 的 fast_video.py；operations video search/resolve/frames与MCP均为该实现的适配入口 | 专用Chrome及固定钥匙包；搜索仅第一页。 |
| 成片上传、入库回查、已授权字段修正 | 已安装的 `rongyao-http-upload`；operations仅计划、票据与统一账本 | 独立upload HTTP会话；不先检查查询Chrome或IAB。 |
| 荣耀AI模型、额度、任务与生成 | 已安装的 `rongyao-ai-generator/scripts/ryai.py` | auto → 固定ensure-ai；AI登录单独验证。生成仍受原票据和费用合同约束。 |
| 明确选择的Chrome/IAB旧上传 | 原分支对应合同 | 只核验该分支；不作为默认HTTP失败的回退。 |

命令路径从当前环境的已安装Skill命名空间定位，macOS本机为 `~/.codex/skills`；目录软链接按真实目标维护。管线内嵌副本和安装包是从维护源生成的分发镜像，不是另一套登录规范。历史归档不参与入口选择。正常任务直接调用相应业务执行器，只有专门诊断才单独调用下面的登录命令。

## 按实际电脑复用登录态

用户于2026-10-23已授权两台电脑分别安全持久化荣耀登录态。按实际HOME／主机识别机器，保留本次业务原入口；普通业务直接执行，不重复运行通用路径诊断、短信能力预检或独立冒烟查询。

| 实际电脑 | 原查询路径 | 原上传路径及失效后的备用认证 |
| --- | --- | --- |
| Mac mini，galw，`RECEIVER_HOME` | 原专用Chrome／新素材2.0查询桥 | 原HTTP上传，保留原人工短信适配器、原群及授权 |
| MacBook Pro，yue，`RECEIVER_HOME` | 原HTTP限定query、视频列表及市场查询扩展；已选Chrome业务仍沿原入口 | 原HTTP上传，保留Mac信息自动接码的60秒唯一新短信规则 |

HTTP命令先复用运行服务；服务退出或满24小时后，先用同级readonly的固定会话助手从本机macOS Keychain恢复readonly／upload各自会话，并核验实际受保护入口。不因服务进程退出重新发码，不因换聊天重新登录，不跨电脑复制Cookie。Cookie变化才保存，原账号密码助手不重建。正常GET遇门户重定向时，可沿同一会话的真实广告链接恢复一次；不提交密码或验证码、不重试写入。网站明确撤销或过期才沿该电脑原接码规则认证；网络、权限和协议错误不清除保存会话、不当作掉线后发码。

`status=ready`或钥匙串条目存在不能替代真实读取成功。MacBook纯SSH冷读钥匙串可能返回-25308；现有HTTP服务仍可直接复用，冷恢复在本机已登录用户的正常桌面安全环境执行原命令。系统仍拒绝时报告具体限制，不改ACL、不自动解锁、不重发验证码。其他电脑只按其实际配置处理，不从两台验收推断具备相同能力。跨天与网站自身有效期仍须实际验证，不承诺平台永不要求认证。

## 已有授权与默认行为

用户于2026-10-11明确要求：复用现有账号配置，固定自动登录方法，实际验证查询及上传入口，以后不要重复询问登录授权。普通荣耀任务内的会话检查、现有账号登录和同一配置恢复直接执行。登录授权不扩大查询范围，也不代替具体上传、投放或其他业务任务。

收到撤销要求，运行 `scripts/keyring.py disable`；停止自动取用凭据，不自动重新导入。此命令只停用钥匙包，不退出已有浏览器会话。恢复必须有用户新的明确指令。

## 固定入口

本 Skill 安装于 `~/.codex/skills/rongyao-keyring`，命令使用当前可用 Python 3：

```sh
python3 ~/.codex/skills/rongyao-keyring/scripts/keyring.py status
python3 ~/.codex/skills/rongyao-keyring/scripts/keyring.py ensure-query
python3 ~/.codex/skills/rongyao-keyring/scripts/keyring.py ensure-ai
```

HTTP查询、市场导出和上传直接使用各自原执行器的保存会话恢复，不预先调用下列Chrome诊断命令。`ensure-query`仅适用于原Chrome查询分支或明确的该入口诊断。

1. 先复用荣耀专用 Chrome 的已有会话。只在原进程确实退出时恢复同一配置；活动进程连接状态未知则停止。
2. 查询执行器已内置登录时直接执行本次查询，不在外部再调用ensure-query；独立查询登录诊断才运行它。`ensure-query` 从本机钥匙串通过固定程序取用现有凭据，在原有正常登录表单最多提交一次，再核验受保护的新素材2.0页面配置。
3. 已登录则不提交密码；验证码、扫码、账号拒绝或系统权限问题保留现场，报告具体阻塞，不循环提交或绕过。
4. 本次任务涉及查询时，确认入口成功后运行对应数据技能；不额外发一条指标冒烟查询。已提交的查询失败不重放。

新素材2.0现有 `fast_video.py prepare()` 已接入钥匙包；MCP工具本机执行链也使用同一凭据入口。MCP隧道404仍须单独诊断，不能当成掉线。

## AI生成后台登录

AI任务直接运行`ensure-ai`，不以查询或广告上传入口的登录结果代替AI登录。此命令复用现有专用Chrome，在必要时通过正常门户登录及实际“AI系统”链接进入，随后读取AI页面模型配置与受保护的视频额度接口；不提交生成。返回`port`和`target_id`供生成CLI连接，账号身份未单独确认时仍标未知。

继续复用原固定钥匙串程序，AI入口由原生已允许的worker分支选择，限定AI与既有广告两个固定主机；不重建程序、不重导入凭据、不导出Cookie或门户票据。门户异步登录最多提交一次，等待明确成功、拒绝、验证码或超时。仅密码框仍存在不能判成验证要求：明确拒绝为`LOGIN_REJECTED`，等待超时为`LOGIN_PENDING_TIMEOUT`；均不重复提交。普通异常先修复工具和入口检查，不向用户重复索要登录状态；真正的验证码、系统权限或浏览器安全阻止不能绕过。

## 查询业务路由

- 消耗、ROI、付费、角色及方向表现：读取 `../rongyao-material-performance/SKILL.md`。
- 筛选、编号、产出数量及分页：读取 `../rongyao-dashboard-filter-finder/SKILL.md`。
- 新素材2.0视频搜索、直链及关键帧：读取 `../rongyao-data-stack/references/video-chatgpt.md`。也可使用隔离执行入口：

```sh
python3 ~/.codex/skills/rongyao-keyring/scripts/keyring.py fast-video search --gid 193 --date-range YYYY/MM/DD-YYYY/MM/DD --material-range YYYY/MM/DD-YYYY/MM/DD --keyword 关键词
```

日期必须替换为本次实际范围；快捷视频搜索仅第一页，不代表全量生产台账。角色、项目身份和业务数据仍按对应技能校验。

## 上传默认路由

其他会话请求普通成片上传时，直接读取 `../rongyao-operations/SKILL.md` 最短路径。upload命令内已独立核验上传登录，必要时由固定钥匙包恢复；不预先运行ensure-query、verify-upload-chrome或CUA检查另一浏览器。已有账号授权持续适用，不再次询问登录授权。verify-upload-chrome仅用于用户要求的入口验收或具体登录故障诊断。

### 上传执行器与原IAB分支

通用成片操作先读取 `../rongyao-operations/SKILL.md`，保留其现行默认HTTP上传路径和本次业务已选接码方式。以下专用Chrome与IAB说明仅适用于明确选择的旧兼容分支，不作为HTTP失败回退：专用Chrome须单独核验完整上传入口，查询Chrome登录不能当成上传入口已可用。兼容通道支持独立上传自动登录，本机现有钥匙包正常恢复无须再次询问登录授权。仅明确选择原IAB时才读取 `../rongyao-video-upload/SKILL.md` 的对应分支并核验该会话；普通CLI不额外核验IAB；不迁移Cookie，不用临时终端POST替代既定上传执行器。

完整表单：`http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video`。

以下IAB步骤只在本次明确选择该原路径时适用，普通CLI不读取或执行。

- 查询 Chrome 已登录不代表 IAB 已登录。用 CUA 检查 IAB 是否实际展示类别、游戏、角色及文件输入控件；入口核验不选择文件。
- 已有 IAB 会话或浏览器已有的原生凭据自动填充可正常继续，不另问登录授权。若 IAB 需要账号密码，只能通过当前工具支持的秘密注入或原生密码填充操作；不得把密码打印给模型或塞入工具调用文本。
- 当前尚无经实测的“钥匙串向 CUA/IAB 保密填充”桥。缺此能力时明确标为该桥未就绪，不反复要求用户授权，不假称完成 IAB 自动登录。
- 内置浏览器工具超时，先查当前标签与最新状态；连续两次同目标失败后按上传技能纠偏。安全策略明确拒绝时停止，不换浏览器或接口实现被拒动作。
- 下列命令在同一专用Chrome独立核验并按需恢复上传登录，只进行正常登录及官方门户跳转，不证明 IAB 登录，不执行上传；该命令不是普通CLI上传前置步骤：

```sh
python3 ~/.codex/skills/rongyao-keyring/scripts/keyring.py verify-upload-chrome
```

## 凭据与维护

凭据保存在 macOS Keychain 固定条目 `com.codex.rongyao-keyring / existing-rongyao-account`。原生固定程序位于 `~/.codex/state/rongyao-keyring/bin/rongyao-keychain`，只运行白名单命令，凭据通过子进程环境使用，stdout只返回脱敏JSON。系统权限拒绝或钥匙串锁定不得绕过；程序变更后可能需要系统再次确认。

`provider.json`仅记录凭据引用，迁移启用后不静默回退到旧 `login.json`。原配置为兼容及回退审查保留，没有复制进Skill或交付包；不要再用旧 `configure-login` 创建不同步的副本。不得未经明确指令删除、覆盖或重新导入凭据。

新电脑只复制Skill源码；无凭据、无登录态。仅在明确初始化授权下运行 `build` 和 `import-existing`，复用该电脑原有配置。`build`遇已有固定程序不自动替换，防止静默破坏钥匙串信任。

查看 `references/verification.json` 获取最近一次验收的入口、浏览器、时间及限制；历史成功不是当前登录证明。`authenticated=true`是受保护入口访问证据，账号身份若无单独证据仍标未知。

上传恢复不先走查询prepare：门户登录后点击实际广告平台链接，URL与内部票据始终留在浏览器。首查受保护上传表单，已登录不提交密码；登录页脚本未完成加载时不得提交。此路径不选择文件，实际提交仍经operations发布与授权保护。

## CLI恢复合同（WF20261016.1）

所有根级/子命令`--help`、`-h`及非法参数在调用固定native helper之前结束，不读取凭据、不登录。AI认证在正常提交前保存本会话检查点；同会话pending/rejected/challenge不重复提交密码，优先沿真实已登录门户进入。结果携带脱敏phase与错误码，不把调试端口失败统称账号掉线。恢复会话返回当前port/target供auto传输使用，正常任务无需用户保持前台。
