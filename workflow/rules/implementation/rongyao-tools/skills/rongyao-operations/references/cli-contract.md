# 命令与清单

默认HTTP提交与回查沿同级 `rongyao-http-upload/scripts/rongyao_upload.py submit --plan ... --workspace ... --authorization-ticket ...` 和 `reconcile --job-id <原job_id>`。`rongyao video plan`、`video inspect-plan`、`job status`共用原账本。下列 `video upload`、`job reconcile`、auth和浏览器字段命令是显式Chrome兼容分支，不是HTTP默认步骤；提交与恢复的唯一主合同见 [HTTP上传](../../../../../../../skills/rongyao-http-upload/SKILL.md#最短路径)；本文件只补计划字段和显式Chrome分支。

```sh
rongyao doctor
rongyao auth status
rongyao auth ensure
rongyao auth ensure --service upload
rongyao auth recheck --service video-list
rongyao video search --gid 193 --date-range 2026/10/01-2026/10/11 --material-range 2026/10/01-2026/10/11 --keyword 家产继承 --limit 2 --refresh
rongyao video resolve --id <搜索返回的ID>
rongyao video frames --id <搜索返回的ID> --count 8
rongyao video fields --game 193 --source-type 小剧场
rongyao video list --name <完整名称或明确前缀>
rongyao video plan --manifest /绝对路径/upload.json --output /绝对路径/plan.json
rongyao video inspect-plan --plan /绝对路径/plan.json --workspace /绝对路径/工作区
rongyao video upload --plan /绝对路径/plan.json --workspace /绝对路径/工作区 --authorization-ticket /绝对路径/工作区/workflow/authorizations/本次票据.json
rongyao job status <job_id>
rongyao job reconcile <job_id>
```

示例日期只是本次真实查询范围；后续改用用户指定范围。`--refresh`绕过30分钟搜索缓存，仍只查第一页。`list`也是第一页，找不到只能说明本次可见范围未发现，不证明全库不存在；官方页面还会在选择文件时自行校验名称。

通用清单：

```json
{
  "test_only": false,
  "shared_parameters": {
    "category_type": "117",
    "ai_source": "SD非拼框",
    "origin_type": "1",
    "demand_name": "示例人员4",
    "source_ip": [],
    "source_type": ["小剧场"],
    "source_direction": ["AI"],
    "gid": "193",
    "role": ["宇智波鼬"],
    "region_type": "",
    "is_redbag": "0"
  },
  "items": [{
    "file": "/绝对路径/本次正式名称.mp4",
    "parameters": {},
    "review": null,
    "provenance": null
  }]
}
```

这组参数仅说明结构，不能默认为任意任务的业务归属。第二设计师空值表示原创；自己的A接别人B时由制作技能提供已核实的第二设计师及37命名。每项`parameters`覆盖共有字段。`filename`可指定新正式文件名，但必须同时使用`--copy-dir /绝对路径`生成命名副本，源文件不修改；内容不同的同名副本不覆盖。

技术要求为H.264/AAC MP4，CLI实际完整解码并记录SHA、尺寸、时长。计划没有冒充视觉、声音审美或用户艺术验收；制作技能的适用广告核查仍须完成。正式名称由本次工作流明确提供，此CLI不猜序号或自动继承旧日期。

`batches`记录完整参数相同的分组；首版传输逐文件执行以便保存各自不确定状态，不宣称并发/断点续传。断线后不能重放分片，当前公开代码没有可据以保证幂等恢复的证据。

## 结果含义

- `PLAN_CREATED`：本地计划已登记，未上传。
- `UPLOAD_CLIENT_BLOCKED`：原浏览器客户端阻止访问；不等于账号掉线。
- `BROWSER_HTTP_CONFIRMATION_REQUIRED`：本次导航触发 Chrome HTTPS 优先模式的原生 HTTP 确认。保留的原标签由用户亲自处理；CLI不代点或改安全设置，完成后再复核原入口。
- `REMOTE_NAME_EXISTS_HASH_UNVERIFIED`：后台同名已存在、无法核对字节；停止，不能覆盖。
- `FILE_SELECTED_PENDING_BACKEND`：已选择文件，官方页面开始流程；尚未验证入库。
- `SUBMISSION_UNKNOWN`：选择阶段后出现故障；不得重传。
- `listed`：本次待核对项在后台列表唯一匹配且有记录ID；不代表元数据详情、播放、审核或投放。

CLI stdout仅JSON。token、Cookie和密码不在JSON、参数、台账或交付包里。SQLite位于本机`~/.codex/state/rongyao-operations/jobs.sqlite3`，计划副本不可手改后提交；修改业务参数应生成新计划。锁和领取操作使用SQLite事务。

## 恢复被客户端阻止的Chrome通道

先解决原Chrome客户端拦截，不能为了完成上传自动修改扩展/安全策略、跨浏览器拷贝登录态或改用HTTP上传。`upload-block.json`没有自动过期重试。

阻塞记录仅代表最后一次失败；普通命令返回 `live_check_performed:false`，不会自动重试。用户明确要求复核时，执行一次 `auth recheck --service video-list`，只在原专用Chrome、原官方列表入口重新导航，检查列表、名称搜索和数量控件，不选择文件。历史记录在请求前保留并写入 `access-history`，只有受保护列表验证成功且没有更新的并发阻塞记录时才解除标记；再次被阻止则更新失败证据并停止。列表恢复不等于上传表单或实际上传验证通过。不要手工删除标记来宣称恢复，也不要自动循环复核。

## 历史Chrome协议证据

以下描述保留原Chrome首版的验证范围：官方页面公开脚本描述先校验名称，再按20MiB分片上传，最后合并登记；当时仅有DOM源码观察，尚未验证真实分片、合并和回执，因此首版复用官方页面逻辑。现行HTTP适配器的执行与实际验收范围以同级HTTP Skill及其verification为准，不能将这条旧版本记录当成当前HTTP未实现或新批次已验收。

## 0.2.1管线合同

提交必须匹配飞书当前工作区发布实现、指定writer、依赖、scope锁及单次input_sha256票据。inspect-plan按UTF-8、sort_keys、紧凑JSON对原登记计划计算SHA256，绑定文件SHA、参数和job_id；JSON空白变化不改变语义，手改内容拒绝。scope固定material-upload:rongyao-operations。旧的无workspace／ticket调用在读文件和接触浏览器前拒绝。查询与回查仍沿原会话；新接口隔离测试与真实上传验收分别记录。

WRITER_HOST_REQUIRED、LIVE_RELEASE_MISMATCH、CIRCUIT_OPEN等已知守卫错误保留代码；不以INVALID_REQUEST掩盖，也不返回原始错误详情。上传认证使用独立受保护表单与权限门户跳转，复用已有钥匙包。MacBook仅可在发布动作列表允许material_upload时提交。

显式Chrome上传按下方兼容合同执行；登录、同名查询、字段读回及运行守卫由该分支的upload命令执行，不在外部重复调用。已有listed交付原ID，受理未知仅回查。日常上传不发布规则包；只有明确维护变更时先验证候选，再一次打包及发布。

原生选框分支的native-plan、native-upload与逐条命令只按需读取native-recovery.md；不以普通plan续接未经绑定的项目助手。


## Chrome兼容提交合同

下列页面和原生选文件流程仅适用于显式Chrome兼容任务；HTTP失败不自动切换到此分支。

本专项使用material_upload权限；生成权限仍按runtime-policy及本批票据核验。上传独立登录：等页面complete，正常提交一次，经门户进入；拒绝或挑战停止。守卫保留错误码。

工作区固定入口为 `python3 scripts/rongyao.py`，调用发布包内同版实现；已安装的 `rongyao` CLI也必须与工作区实现SHA吻合。沿钥匙包复用现有专用Chrome，认证不索取私有请求文件；不迁移Cookie、重放分片或调用页面私有上传函数。

1. 续接先 `job status <原job_id>`；同一账号配置且已listed交付原ID，受理未知只回查。新文件才一次 `video plan --manifest ... --output ...`；原登记计划及文件未变直接复用，技术与音画验收证据也不重复生成。
2. `video inspect-plan --plan ... --workspace ...`取得input_sha256，依据本次真实上传请求生成material_upload / material-upload:rongyao-operations短期票据；票据不能用于重传受理未知文件。
3. 一次 `video upload --plan ... --workspace ... --authorization-ticket ...`。命令内完成同版、主机、依赖（包括实际安装的钥匙包及数据栈文件SHA）、锁、文件SHA、本地/后台查重、独立钥匙包登录及全部字段读回，再原生选文件。file selection前持久化selection_pending；之后故障仅回查，不能换票据重传。fields仅字段缺失才查，不要求外部先list或auth检查。
4. 按官方处理间隔（当前约两分钟）后 `job reconcile <原job_id>`；完整名称唯一匹配并有ID才listed。未入库或多个匹配继续待核对，不重传。已于2026-10-12单文件实测ID124887；其他批次仍逐批验收，详情、播放、审核另验。

## 兼容命令的边界

- 新素材2.0检索、直链、关键帧：`video search / resolve / frames`，沿用现有只读执行链；搜索覆盖第一页，不能冒充全量台账。日期、游戏和关键词使用本次任务范围。
- 已命名的完整成片：`video plan` 接受通用清单，无须虚构A/B来源或37分成。用户要求接片/生产时先用 `../../rongyao-video-upload/SKILL.md` 完成加工和正式命名，再把成片路径、完整表单参数交给此CLI。不要用通用计划跳过已适用的加工和画面核查。
- 视频列表按实际卡片/行内的ID与名称成对读取，校验页面总数；总数大于零却未解析出记录时返回结构错误，不得当作无同名素材。该CLI仍只覆盖第一页，全周产出应使用周报工具逐日完整分页。
- 字段和后台列表：`video fields / list` 在同一查询专用Chrome会话内读取完整官方页面。依赖字段按游戏→角色、一类→二类处理；输入必须使用页面实际值。火影分类117与忍界大战游戏193是两个字段。
- Chrome兼容上传（仅用户明确选择）：`video upload --plan ... --workspace <工作区绝对路径> --authorization-ticket <票据绝对路径>` 使用已登记的原计划，重新核对文件SHA、检查本地提交记录和后台同名记录、读回全部字段，然后通过Chrome原生文件输入选择文件。页面自行执行官方上传逻辑；不复制Cookie、不导出token、不重放分片请求、不调用页面私有上传函数。该CLI不会另开浏览器进程，但会建立临时后台标签。
- Chrome兼容分支的文件选择立即触发上传。具体批次“上传”请求已覆盖正常选择和提交，不重复询问；只做入口验证时不选择文件。缺文件先查access目录和当前任务产物，仍不明确才集中询问路径/参数，不能重传历史素材测试。

## 兼容分支、历史验收与维护细则

下列原合同按本次显式Chrome、原生选框、历史溯源或维护需要读取；日期是对应历史证据时间，不表示本次业务已验收。默认HTTP提交仍只沿HTTP执行器，失败不自动切换。

## 当前验收状态与停止条件

2026-10-11：原专用Chrome的视频列表入口已恢复并通过真实查询；本周火影117统计共161条，七天9页、唯一视频ID161，页面总数、保存文件与服务接口一致。已修复原页末页符号和重复page参数的分页适配，以及CLI把卡片布局误当表格行、返回空列表的问题。查询会话和真实新素材2.0搜索已验证；通用计划、SQLite去重、选文件前持久化检查点和本地Chrome夹具已验证。历史客户端拦截已归档，当时真实CLI上传尚未完成；2026-10-12已通过一次真实上传，官方记录成功且原Chrome列表唯一匹配素材ID124887。该单文件测试未验详情、播放或审核，不扩大为其他批次通过。

`doctor`/上传相关命令读取阻塞记录后停止。记录代表最后一次失败，`live_check_performed:false`，不能据此断言此刻仍被拦截。用户明确要求重新核验时，可执行一次 `auth recheck --service video-list`：在原专用Chrome访问原官方列表、核验受保护页面结构，成功后才解除标记，并保留历史证据。该命令不证明上传表单可用。不能自动循环重试、换浏览器、绕过客户端规则、取Cookie或切换HTTP接口；查看 [references/cli-contract.md](cli-contract.md)。验证码、原生权限、平台拒绝分别报告，不混称账号退出。

Chrome 的 HTTPS 优先模式可能对该 HTTP 后台显示原生安全确认，并同时返回 `ERR_BLOCKED_BY_CLIENT` 和空白错误页。CLI按本次导航前后 `Security.HttpsFirstMode.InterstitialReason` 计数增量识别为 `BROWSER_HTTP_CONFIRMATION_REQUIRED`，保留原标签供用户处理；不关闭确认页、不代点安全警告、不改全局 HTTPS 或证书策略。历史计数不能单独作为本次原因。2026-10-11原Chrome已有该站HTTP确认记录后，视频列表入口复核成功，历史停止标记已归档解除；当时实际上传未验证；最新单文件入库证据见references/verification.json。

## 任务状态

`plan`只完成本地技术检查和参数分组，字段有效性、后台查重、画面验收不能自动标成通过。`test_only:true`计划永不允许外部上传。

上传前，CLI把名称/SHA/参数登记到本机SQLite。在选择文件之前提交 `selection_pending` 检查点；之后任意连接中断均保留待核对状态，禁止自动重试。不同任务不能同时领取相同名称；同名不同SHA、同文件不同归属都停止。后台已有同名但无法验证SHA时停止，不能猜成同文件。

显式Chrome兼容分支在页面提示处理间隔后运行一次 `job reconcile`；默认HTTP使用其 `reconcile --job-id`。两者均须：完整名称唯一匹配且有记录ID才标为 `listed`；暂未出现或匹配多个保持待核对。不每几秒轮询，不因详情或播放打不开重传。该版本只核对列表ID，**归属详情、播放、审核和广告发布均另计**。生产执行的页面结果按当前工具能力保存原生截图，不伪造截图。

用户更换荣耀账号/Chrome配置时，旧上传台账不能沿用为新账号的成功证据。没有独立身份核验时保持 `account_identity_verified=false`，不扩张为跨账号自动操作。

命令、清单及实际已发现的协议边界见 [references/cli-contract.md](cli-contract.md) 与 [references/observed-upload-protocol.json](observed-upload-protocol.json)；最近验收证据见 [references/verification.json](verification.json)。

## 当前管线接入与Chrome兼容接口

WF20261015.1提供固定入口`python3 scripts/rongyao.py`；全局入口提交前验证自身SHA与该工作区发布实现一致。先用`video inspect-plan --plan <已登记计划绝对路径> --workspace <工作区绝对路径>`取得完整计划input_sha256；本次真实上传授权的票据沿workflow_runtime生成，action为material_upload，scope为material-upload:rongyao-operations。上传必须同时给workspace和authorization-ticket；writer、当前飞书版本、依赖、scope锁、熔断和单次票据校验均在选文件前完成。无offline提交选项。原本机SQLite和受理未知保护保留；不能因换新票据重传待核对文件。接口及隔离验证不代表真实新批次上传、详情或播放已经通过。查询、本地计划、只读inspect-plan及原作业回查不授予提交权限。

仅显式Chrome兼容上传入口由钥匙包独立恢复：先复用受保护上传表单，登录失效时在同一Chrome正常账号密码表单最多提交一次，再点击权限门户真实广告后台链接并核验完整表单。须等登录页complete后提交；挑战或明确拒绝保留现场，不自动重试。MacBook receiver-host.invalid允许material_upload及已授权的paid_generation；不取得状态回写或商业发布权限。已知守卫错误保留结构化错误码，不输出原始含路径错误详情。

## 原生选框与恢复的发布入口

本批明确采用原生辅助功能选框时，按需读取[恢复合同](native-recovery.md)，使用当前工作区的native-plan／native-upload；不重放项目历史助手。两次无效跨进程计数，取消不算提交，未知不降级重选，源码或二进制改变使原计划失效。仅查能力或整理／安装不选择文件；已有入库及待核对文件不重传。真实新批次上传、详情和播放仍单独验收。

当前同版部署检查包含实际执行的rongyao-keyring、rongyao-data-stack及同目录依赖，保留并纳入已有AI入口与异步登录实现的文件哈希。原生Open提交前复验当前文件SHA、唯一完整选中路径与全部可见字段；字段或文件改变即停止，细节按需读取references/native-recovery.md。上述原生选框分支保留工作区控制器与发布依赖守卫，不重复历史视频实网测试。

## 全局入口同源转交（WF20261016.1）

全局`rongyao video upload`先校验自身与工作区正式实现SHA及wrapper哈希，再在选文件前将同一进程转交工作区固定入口。计划、作业ID、票据与SQLite账本保持原件，继续通过原runtime守卫；不因转交重新建job、不放宽调用路径、不重试受理未知文件。

## 0.2.3 内容与归属维护

计划先核对字节SHA、同批重复内容及制作编号，再完成技术验证与上传副本。单文件可用inherit_from={job_id,filename}继承已登记来源的全部参数，优先级为单文件parameters、shared_parameters、来源参数，最后仅需求人缺省为原创。来源计划SHA及shared_provenance保留在逐项provenance；不凭人员尾码推定后台ID。内容／编号去重在Ledger.claim同一写事务再次执行，供HTTP与原兼容入口共用。完整合同与失败恢复见同级rongyao-http-upload现行Skill及其manifest；1.1.0是该维护合同最初对应版本，不用于判断当前安装版本。
