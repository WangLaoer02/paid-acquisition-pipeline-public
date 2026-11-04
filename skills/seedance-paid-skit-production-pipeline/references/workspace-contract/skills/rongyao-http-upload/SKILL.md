---
name: rongyao-http-upload
description: 荣耀已验成片的默认无浏览器上传与登录恢复。复用本机HTTP上传会话，服务退出先从本机Keychain恢复，网站会话确实失效后才沿原短信登录；核验字段、统一账本查重、原生分片合并和入库回查。用于素材上传、上传器要求登录或明确不要浏览器/扫码的任务。
---

# 荣耀HTTP上传与会话恢复

账号复用、机器差异与登录恢复选择统一按已安装的 `rongyao-keyring` Skill；本文件是HTTP提交、归属验收及未知受理恢复的唯一主合同。日常直接使用本执行器内的会话恢复，不预跑查询Chrome或IAB检查。

此独立扩展补充原上传器，默认采用直接HTTP，不打开或连接浏览器。用户明确上传请求覆盖原账号正常登录及该批提交，不重复索取验证码或扫码。提交、恢复与入库判定统一以本文件为准；operations只补计划/账本命令，material-upload只补业务输入与验收。源码与飞书发布入口按本节附件安装；认证复用同级rongyao-http-readonly的短信消费进程，但上传服务与只读服务的socket及权限分开。

## 最短路径

计划与账本命令使用 `rongyao`；不在PATH时用 `python3 ~/.codex/skills/rongyao-operations/scripts/rongyao.py`。已有计划和账本未变直接续接。新文件的清单格式、继承关系或复制命名需要补充时才读取 [计划清单](../rongyao-operations/references/cli-contract.md#命令与清单)，不要求先读另一份提交主控。

1. 真实管线item按原节点合同核验；独立已验文件不虚构item。核对本次文件及授权，先查原rongyao-operations作业/账本。有listed交付原ID，有受理未知先辨明原回执transport：direct_http_sms沿本HTTP执行器，历史Chrome沿原兼容回查入口；来源不明先定位，不能跨传输重传。文件内容与制作验收不因换认证重新生成。
2. 运行 `scripts/rongyao_upload.py status`，没有有效上传会话才 `start --output-dir <本次目录>`。先从本机Keychain恢复并核验受保护入口；只有网站会话明确失效才沿本机既有接码方式认证，默认不扫码、不退回Chrome。`fields --gid <游戏ID> --source-type <一类>`只在缺实际枚举时查询；prefix核对本日编号，不猜编号。
3. 仅新文件，或已证明未发送且用户明确采用的纠正，才用原 `rongyao-operations` 的video plan创建并登记真实成片计划；已有登记计划及文件未变则直接复用并inspect-plan取得input_sha256，沿原workspace runtime生成material_upload／material-upload:rongyao-operations单次票据。提交前同版原规则、writer主机、依赖、锁、票据、注册计划、文件SHA及新扩展源码manifest全部核验。
4. `submit --plan <计划> --workspace <工作区> --authorization-ticket <票据>`：同一账本原子认领、同名/同SHA跨聊天检查、当前后台查重、原生名称预检、全部字段核验，然后20MiB原生分片和合并各提交一次。文件内容只读取固定快照；Cookie由固定原生助手安全保存在本机Keychain，隐藏表单认证值仅留服务内存。
5. 收到submitted_pending不报完成。先立即执行一次 `reconcile --job-id <原job>`；尚未入库则按返回的`next_lookup_at`续查（保留原约120秒处理间隔与服务端Retry-After），不固定空等，唯一完整名称与同记录ID通过才listed；详情读回另标。超时或分片/合并受理未知保留submission_unknown，不能换名称、换票据、换认证或换传输重传。

## 业务默认

用户2026-10-17明确：没有明确归属来源时，需求人使用“原创”，制作编号前缀D；已有明确来源优先。保留原文件，使用上传副本。末尾渠道/人员段按当前已验证命名规则，不由D猜账号ID。

当前需求人下拉未列“原创”，用户明确指定时可在计划provenance记录requester_explicit_original_override=true，提交这一文字并独立回读。不是默认套用页面中的第一个需求人，也不扩张为任意未列值。AI字段使用实际制作方式及有效选项；后台无对应工具时说明空值表示当前枚举“无”，不冒填SD或H3。

## 失败与验收

短信来源绑定、系统读取权限及现有Keychain沿同级认证Skill处理；缺项报告具体原因，不改系统权限或导出登录数据。上传服务只接受固定命令与白名单原生端点，拒绝任意URL、写入重定向和写入重试。只读服务仍不提供提交命令。

新登录、上传受理、列表入库、详情字段和远端播放分别记录。成功必须实际入库ID与完整名称唯一匹配；HTTP200、分片ACK或合并ACK不算入库。详情或播放失败不重传。原生成、广告发布及项目采用状态各沿原合同。

安装见README.md；operations共享账本与本扩展一起按发布清单校验；本扩展另用独立manifest验证自身。源码改动需重新测试并更新扩展包；原runtime不会因本扩展而跳过其既有守卫。

## 1.1.0 维护合同

- 内容去重使用文件字节SHA-256；它不等于画面相似度或远端文件SHA验收。计划阶段先拒绝同批同内容不同名，账本认领在同一SQLite写事务核对跨作业内容、完整名及制作编号。已listed沿原ID；selection_pending／submitted_pending／submission_unknown只回查，批次再次提交会跳过这些项并返回原job，不重发。
- 归属使用单文件parameters ＞ shared_parameters ＞ 单文件inherit_from指定的已登记来源 ＞ 缺需求人时原创。inherit_from必须为{"job_id":"原作业","filename":"原完整文件名.mp4"}，来源计划SHA进入provenance。shared_provenance与单文件provenance合并；显式空AI值保留。原创默认不自动获得未列枚举override；其他缺字段仍须补齐，不从D或末尾人员码猜账号。
- 制作编号按已验证前缀识别，同批和账本重复编号即停止。prefix只给候选，不占号；原生getVideoNames仍是最终冲突检查。返回NATIVE_NUMBER_OR_NAME_CONFLICT后保留原计划、文件与回执，明确采用新编号后才能建新计划；未知受理永不改号重传。证明字节未发送的blocked_before_selection允许修正；preparing不能因后台同名就补记成功。
- 回执按job＋完整名哈希逐文件保存，保留明确错误码、分片／合并检查点。服务源码更新后旧进程返回UPLOAD_SERVICE_RESTART_REQUIRED，正常重启认证服务后仍沿原账本和原job恢复。
- 列表回查不加归属过滤，必须取得完整计数、唯一ID与精确全名。分页未覆盖返回LIST_REQUIRES_PAGINATION，不能当零记录或唯一记录。详情读取成功仅记detail_readback_verified；逐字段matched／missing／mismatch独立记录，metadata_verified不由读取成功推定。已listed但详情失败可再次reconcile补读详情，绝不重传。

本版本只用隔离夹具验收；历史真实上传证据单独保留，不能算作新版本实网验收。

## 本机免短信恢复（2026-10-23）

用户已授权将本机有效HTTP登录态安全持久化。日常直接执行原命令：优先复用当前服务；服务退出或满24小时后，从本机独立Keychain会话条目恢复并核验实际受保护入口，不发验证码、不提交密码。网络错误和权限错误不当作登录过期。网站确实撤销会话后，才沿本机原自动接码登录；仍只发一次，不自动重发，不改60秒唯一新短信规则。不会从别的电脑复制账号或Cookie。

会话仅由固定原生助手通过私有管道读写`com.codex.rongyao-http-session`下readonly／upload独立条目，磁盘、socket、报告和安装包无Cookie明文；原账号Keychain程序与条目保持不变。查询、市场导出、上传票据与账本及受理未知处理沿原合同，不因恢复而重放查询或上传。状态内cookies_persisted=true且受保护读取成功才算当前可用，跨天效果另验。

本机实际验证：2026-10-23，查询原命令及上传fields各通过两轮停服自动恢复，原市场受保护入口也通过，全程未发短信、未提交密码、未上传视频。登录态来自本机原HTTP进程；原账号助手哈希不变。跨天效果待另行验证。纯SSH环境读取登录钥匙串可能返回-25308；已运行服务可直接复用，冷恢复应在本机已登录用户的桌面环境执行原命令。这是系统交互环境限制，不当作网站掉线，不据此重发验证码，不自动解锁钥匙串或修改ACL。

已知机器和业务直接执行原入口，不增加通用路径诊断或每次短信能力预检。有效会话直接完成本次正常读取。仅广告后台GET被重定向到原门户时，在同一内存会话中沿门户真实广告链接恢复一次，再继续原读取；不提交密码/验证码，不重试POST或上传字节。门户真正出现登录表单才返回LOGIN_EXPIRED，并将内存状态标为login_required；本机人工短信与另一台Mac自动短信仍沿各自原规则。网络、权限、页面变化不能统称登录失效。

## 1.2.0 主设计师与完整业务验收

主设计师、需求人、第二设计师分别核验。不得新增并不存在的 `parameters.designer`，不得改写登录隐藏字段 `create_name`，也不得从首段或尾码猜主设计师。逐文件计划使用已有 `provenance.source_native_fields["设计师"]`；独立委托可用 `provenance.designer_name` 和 `designer_source`（具体用户指示/原记录来源）。显式值与原详情冲突时必须有 `designer_override_authorization`。这些字段纳入原计划 SHA；缺来源在任何视频字节发送前停止。

上传表单没有独立主设计师选框。原生入库后可能仍显示上传账号；后台真正的修改动作为详情页 `saveDesignName`，字段只有原素材 ID 与 `design_name`。因此完整执行是：原 submit 一次 → 原job立即reconcile一次，未入库按next_lookup_at续查 → 原 ID 已 listed 时执行一次受票据保护的 `finalize-attribution` → 新鲜只读回查。不为修归属重新上传。

```bash
python3 scripts/rongyao_upload.py finalize-attribution --job-id <原job> --workspace <原工作区> --authorization-ticket <本次归属收尾票据>
python3 scripts/rongyao_upload.py reconcile --job-id <原job> --refresh-details
python3 scripts/rongyao_upload.py detail --name <完整名称.mp4> --record-id <原ID>
```

归属收尾票据仍沿原 runtime，action=material_upload、scope=material-upload:rongyao-operations、input_sha256=原登记计划摘要，审批引用沿当前已授权批次或具体直接修复指示；原上传票据已经消费时，为归属收尾生成新的单次票据，不重复请求同一业务授权。该命令只允许已 listed 的原名称/ID，提交前后核对完整详情及媒体地址，已经正确则只读验收；设计师变更受理未知先读回，绝不自动重放，不触碰分片或合并。

`reconcile` 保持远端只读，不会悄悄改设计师。它将 listed 与 all_metadata_verified 分开；缺主设计师或任何可见业务字段，metadata_verified=false。必查分类、所用AI、创作类型、需求人、主设计师、第二设计师、角色、一二类、素材IP；AI 选项与第二设计师枚举转为页面文字后比较。“类型”按用户指示默认忽略，实际尺寸另验。隐藏 gid/is_redbag 未独立暴露，不冒称 all_parameters_verified。AI 标签匹配不等于已追溯实际生成工具。

需求系统登录与上传列表登录分开报告。详情需要时只沿同账号权限门户实际的 demand 链接绑定会话，SSO链接仅在服务内存，不保存或输出；荣耀Cookie按本机授权保存到钥匙串独立会话条目，不打印或写明文文件；门户失效报 DEMAND_LOGIN_REQUIRED，不误报所有上传登录失效。升级后旧服务被源码守卫停止，正常恢复新服务；已入库仍沿原 job/ID 回查。

## 1.2.1 macOS 常驻服务恢复

固定业务主机的请求显式禁用系统代理自动探测，避免登录进程 fork 后触发 macOS `_scproxy` 崩溃；保留内存 Cookie、端点白名单、不重定向写入和不重试写入。RPC 空连接报服务连接关闭，提交端沿原 job 查账及回查，不把断线当失败重传。手动短信接收窗口、父进程等待与群消息新鲜度统一为10分钟；超时不自动再次发码。

## 1.2.2 已列记录改名接续

已有后台记录被改名时，保留原账本名和作业，不能因旧名查不到再上传。对已核远端SHA的原ID，新建仅元数据收尾的登记计划，参数和文件SHA沿原作业，provenance.operation=existing_id_designer_reconciliation_only。listed_native_identity 固定原record_id、ledger_name、实际native_name（含.mp4）、sha256和刚核实的media列表；原生列表按当前完整名查回仍须唯一同ID，详情媒体须一致。finalize-attribution仍受原runtime票据和原参数保护，只改主设计师；独立元数据计划不能submit。验收后原回执保留verified_native_identity和designer_intent_plan（实际登记作业及摘要），以后原作业reconcile按已核名称读原ID，并从冻结的归属证据计划取主设计师意图。没有明确别名与证据时继续严格报错，不猜名称或放松SHA/ID守卫。

## 1.3.0 重启恢复登录态

用户已授权本机安全持久化会话。沿原HTTP路径保存到同级readonly的独立原生钥匙串会话助手；不改原账号密码助手，不跨机器复制会话。正常成功请求只在Cookie变化时更新钥匙串，不增加网络诊断。原命令找不到服务时先恢复并验证保存的上传会话，再执行本次请求；仅证明请求尚未交给任何服务时才继续，空连接、未知受理和已提交写入从不因此重放。

服务单次仍默认24小时，退出或电脑重启不会主动删除钥匙串会话；平台失效才沿本机原人工/自动短信规则认证。需要首次初始化但没有真实上传批次时，可用同级`session_store.py initialize --service upload --output-dir <目录>`进行仅认证初始化：本机隐藏输入一次短信码，不制造批次、不授予上传权限、不改变原群人工备用入口。恢复、认证、上传受理、入库分别验收，钥匙串保存不等于当前后台已认证。

## 1.3.2 空闲会话保持

启用自动上传后，原120秒worker在队列为空时也读取status；服务每15分钟最多一次原生受保护表单GET并持久化轮换Cookie。原进程24小时退出后仍由Keychain恢复验证，不发码、不重试视频写入。平台真正要求验证码时沿该机原认证分支：MacBook自动接码，Mac mini保留原人工/群备用；不承诺永不失效。

## 1.3.3 门户与失败原因接续

上传空闲刷新同时沿原同账号门户与广告链接读取，保持后续需求端详情SSO所需的门户会话；只读GET，不发送密码/短信、不重放视频提交。最新恢复诊断保留最近一次明确门户认证失效原因，即使后续空会话轮询也不抹去，便于定位。平台真实失效仍沿本机原验证码路径。

## 1.3.5 已有原ID字段修正

明确授权的已有成片字段修正沿 `correct-metadata --job-id <仅元数据登记计划> --workspace <原工作区> --authorization-ticket <单次票据>`，不执行submit，不补记为本上传器的新提交。runtime.mutation仅在原已登记upload_service.py入口内执行，辅助模块不建立独立写入口。计划逐项provenance.operation=existing_id_metadata_reconciliation_only；metadata_correction固定原record（id/name）、媒体地址、完整before_fields、用户逐字段changes（before/after）及authorization（evidence_file/sha256）。登记计划及本地成片SHA、实际原ID和媒体、修正意图、全部未改字段、用户证据文件摘要及原runtime守卫共同核验。

仅需求人、第二设计师和角色标签三种已观测原生动作，调用前重新核对详情JS与真实枚举；第二设计师用原生ID，角色用tag[]序列。每字段发送前持久化SENDING，ACK后立即读回原ID、媒体及完整字段，再写VERIFIED。断线或受理未知保留检查点；后续只读辨明，不重发未知写入。已经符合期望只读跳过。最终十项可见业务字段验收后才完成，不改原素材、不重传视频、不改名、不触碰广告发布。

准备检查可用`probe --session <明确原会话>`：仅一次10秒上限的原生表单GET，不恢复登录、重绑SSO或保存Cookie；动态角色/方向枚举与上传归属仍在原受守卫步骤核验。
