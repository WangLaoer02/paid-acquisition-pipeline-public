# Premiere 本机最小桥 0.2.1 候选

规则入口始终为飞书工作流中心；本目录是执行实现，不是第二套业务规则。

历史 0.1.0：2026-10-12 在现有 Premiere 26.5.2、SK005 工程独立副本完成 UXP `EncoderManager.exportSequence(..., IMMEDIATELY, output, preset, false)` 实测。A 段 720×1280、24 fps、450 帧、18.75 秒，三句字幕烧录；实际音轨与已采用 V005 的相关度 0.999993，前 12.5 秒配乐与原 WAV 相关度 0.999927。完整解码通过，原工程 SHA 不变。此证据不替代新的完整人工听审或用户采用。

历史 0.2.0 验证时用户曾允许开启插件开发模式并重启 PR，明确禁止更新 Adobe；这不是后续维护的新授权。未更新 Adobe 应用；初次 UPIA 安装因 Creative Cloud 更新提示而终止。当前为本地开发插件加载，不是商城安装。PR 重开后，无阻塞任务时执行下面的 start，重新加载桥。开发模式不能由脚本偷偷开启。

0.2.1 仅为本地候选，未覆盖正式固定副本，也未在真实 Premiere 部署验收。历史 0.2.0 的宿主成功不证明当前插件在线或本候选通过原生验收。

## 当前机器使用

PR 需已经运行，当前安装的 Adobe 官方 CLI／x64 Node 工具链位于同目录 tooling，版本与唯一发现兼容修改见 TOOLING.json。

```sh
python3 workflow/tools/premiere-bridge/manage.py start --scope '/绝对路径/本轮验证目录' --original '/绝对路径/受保护原工程.prproj'
python3 workflow/tools/premiere-bridge/bridge.py submit --request '/绝对路径/任务.json'
python3 workflow/tools/premiere-bridge/manage.py status --job '唯一任务ID'
python3 workflow/tools/premiere-bridge/manage.py stop --scope '/绝对路径/本轮验证目录'
```

只支持 inspect、snapshot-copy、open-copy、export-a、restore-original。复制工程与输出必须在 scope 下；原工程仅用于身份校验和恢复打开。snapshot-copy 在原生 PR 内另存副本；export-a 必须先在同轮 snapshot-copy 或 open-copy 建立候选 SHA／工程 GUID 绑定。另存本任务自动生成的新 save_path 后再直导，保留原候选及未保存内存，不再原位 save。任务被领取后持久化认领，重载不重放；超时先查同一任务和输出，禁止新 ID 重传未知任务。

export-a 请求包含 id、copy_path、expected_copy_sha256、sequence_guid、in_seconds、out_seconds、output_path、preset_path、preset_sha256、require_captions。默认要求烧录字幕和音视频。控制器补齐 protocol、bridge_version、project_guid、expected_original_sha256 及独占新 save_path；这些值不可从旧项目复制。先按工程实际画幅／帧率制作预设：

```sh
python3 workflow/tools/premiere-bridge/make_preset.py --width 720 --height 1280 --fps 24 --output '/绝对路径/本轮新预设.epr'
```

使用当前安装 Adobe 自带 shareforreview-h264.epr 的现行 CaptionParamContainer 格式，绑定 SHA。旧 Frame.io v4 的 Captions 参数会漏掉新字幕；工程内嵌 AMEPreset 不能直接另存为 EPR（实测触发原生预设读取崩溃），手工展平也不采用。此版本实测空预设／省略参数的 applied-settings 直导均被拒绝，因此只允许显式有效 EPR。

实际输出必须做 ffprobe、全解码、字幕画面和真实音轨检查，不能以 true 或文件存在代替。verify_export.py 是 SK005 验证工具，固定的 18.75 秒等断言只能用于本案例；其他项目按当前节点合同调整。

## 通信与安装范围

插件 manifest 只请求 localFileSystem: plugin，无网络、全盘、剪贴板、shell、eval 或原生 addon 权限。控制器将任务写入插件自己的只读目录，插件回执写入自己的 PluginData；外部程序读取回执。Python 控制查询只监听 127.0.0.1，拒绝外部网页 Origin；不是任意脚本执行端口。

UXP 官方 CLI 1.2.0 的发现列表较旧，唯一修改是加入 premierepro／PPRO；官方 native helper 为 x64，使用已核验的 Node 24.21.0 darwin-x64 和现有 Rosetta。没有修改 Adobe 应用二进制或关闭证书校验。tooling 的厂商运行时不打入源码包；新机器必须先部署这些官方依赖、取得开发模式许可并独立复验，不能把本机成功视为别的机器已安装。

依据：[Adobe 开发工具](https://developer.adobe.com/premiere-pro/uxp/introduction/essentials/dev-tools/)、[插件沙箱文件](https://developer.adobe.com/premiere-pro/uxp/resources/recipes/filesystem-operations/)、[官方 PR 直导示例](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/src/export.ts)。

## 0.2.0 写前检查与恢复

snapshot-copy 的 copy_path 必须不存在；入队及实际执行前各检查一次。export-a 强制非空 sequence_guid，插件无条件与活动序列比较。候选在同轮打开／快照后改变时，重新读取并原生打开；禁止仅更新 expected_copy_sha256 绕过旧内存保护。导出只另存独立新 save_path，原候选不写。写前 save 许可和 export 许可经插件沙箱握手，各仅签发一次、3 秒有效；核对原件、候选、预设、输出，保存后再核对。许可丢失、超时或本机状态改变时回查原任务，不重放；许可文件保留在本轮插件目录。

原生副作用之前的明确拒绝为 failed；saveAs/open/exportSequence 之后异常为 unknown。控制器根据已持久保存的许可与事件保留占用，不信任迟到 failed 释放任务。unknown、verification_required 会阻止新任务、停止或重载；控制器重启恢复同一 scope 的 bridge-jobs，不会重发已领取任务。旧协议的 export-a failed／native_call_returned 必须重新核对，不能凭旧状态继续。控制器每个 scope 使用进程锁，旧插件版本不接受新任务。

原生调用 true 仍为 verification_required，执行 `bridge.py verify --job <原ID>` 核对原件／候选／导出副本 SHA、音视频流、时长、完整解码和稳定输出 SHA，才记录 completed（只代表技术检查，content_acceptance=false）。返回 false 或异常不能仅凭文件存在通过。

unknown 恢复时，先查询原任务回执和真实 PR，确认对应原生任务已终止；禁止另开 scope、换 ID 或重发旧请求规避未知任务。没有终态证据就保持 unknown。确认后使用 `bridge.py verify --job <原ID> --terminal-evidence <本轮JSON>`，JSON 必须包含 job_id、native_terminal_confirmed=true、observer、observation、evidence_path、evidence_sha256 和 outcome（completed／failed）。证据须是实际宿主观察或原生终态回执，不能拿人工意图当终态。completed 仍校验真实输出；failed 必须无输出，已有部分文件时先审查保留。快照／打开的未知结果也要求原任务终态证据。证据不替代用户采用，也不授权恢复已停止生产。

控制器意外停止时，只重启 `bridge.py serve --scope <原scope> --original <原件> --mailbox <原插件bridge-job.json> --receipt-dir <原PluginData>` 读取持久回执并核验，未解除未知前不运行 manage.py start 重载插件。不得删除 bridge-jobs、认领记录或许可来重试。插件自身无网络及全盘权限，版本 0.2.0 保持原权限范围。

0.2.0 验证：20 项隔离异常／正常用例使用原控制器和插件文件传输，仅替换 Adobe 宿主；当前 Premiere26.5.2 独立副本保存、重开、18.75 秒直导及全解码通过。测试片不作为新业务采用或上传。完整证据沿既有维护记录，本次用户手改和历史素材保留。

## 0.2.1 活性与同 ID 只读恢复（候选）

`manage.py status` 返回 controller 和 `plugin_health`。控制器启动时在自己的插件目录生成一次随机握手 ID；插件轮询写回该 ID、真实邮箱路径、插件 session、enabled 和时间戳。只有版本一致、当前握手/邮箱一致、心跳不超过 6 秒且非未来时间，才接受新请求或派发 queued 请求。旧 ready 文件、文件 mtime、服务端口在线和历史成功均不算当前活性。原生调用占用期间心跳可过期；这表示暂时无法证明轮询活性，不证明原生任务已结束，不解锁 unknown，也不触发自动重载。

正常 `start` 仍拒绝所有阻塞任务。对于唯一阻塞的、仍为 queued 或 dispatched 的 inspect，可用受限入口：

```sh
python3 workflow/tools/premiere-bridge/manage.py recover-inspect --scope '/原scope' --job '原inspect-ID'
python3 workflow/tools/premiere-bridge/manage.py status --job '原inspect-ID' --detail
```

该入口要求控制器/插件均已通过正式部署到 0.2.1，且控制器邮箱就是当前安装插件的邮箱。它拒绝混版/不同邮箱，不负责发布、迁移、启动或停止服务，不改变 Adobe 开发模式。恢复前需同时满足：插件心跳已失效；只有此任务占用；request.action 为 inspect；无 events/result/save/export 许可或副作用标志；原 PluginData 中有效 claims 列表不含此 ID；回执不存在。dispatched 必须原邮箱 JSON 与持久 request 完全一致。queued 尚未派发，邮箱必须为空/不存在或只包含另一条已认领 ID；恢复检查不派发、不改状态，插件重新在线后仍由原队列首次派发同一请求。缺失或损坏 claims、部分/损坏回执、已认领、accepted/unknown 和任何写任务均拒绝。

控制器只追加恢复观察（claims/mailbox SHA、时间、未认领/无回执），不改任务状态或 request。管理器在重载前再检查一次，然后通过原官方 CLI 加载同一插件，保留邮箱字节和全部 claims/许可/回执，等待同 ID 返回。插件允许 protocol 2 / 0.2.0 的 **inspect** 只读请求原样完成；其他旧版动作不享受兼容。认领竞态由持久 claims 再次挡住；重载后已认领但无回执会继续占用，不重试执行。读 claims 失败不再当成空列表。文件存在性使用 Adobe 公开的 [Folder.getEntries](https://developer.adobe.com/premiere-pro/uxp/uxp-api/reference-js/modules/uxp/persistent-file-storage/folder) 接口，不以捕获全部读取异常冒充“不存在”。

恢复成功必须看到该原 ID 的真实 `native_call_returned` 和当前工程/序列信息；`plugin_health.ready=true` 或 CLI load 成功不算 inspect 成功。10 秒未返回时输出原任务和未恢复状态，仅回查原 ID。不存在自动超时释放、取消 claim、伪造回执或允许新 ID 重试的分支。已认领失联仍沿原终态证据流程处理；本版本没有增加其重放或清锁权限。

### 旧控制器迁移与发布边界

仅 `dreamina-round1-readonly-inspect-20261104` 的旧 0.2.0 未认领 dispatched inspect 可用 `migrate_inspect.py plan/apply`。正式发布并完成新固定副本完整性核验后才允许 apply；plan 只读，五分钟有效，apply 必须显式传本次计划 SHA。入口现场核对旧桥代码 SHA、PID/owner/启动时间/完整启动参数、scope、original、唯一阻塞项、原请求、全部 jobs/claims/receipts/permits；任一未知、写动作、执行证据、缺失/损坏 claims、回执或手改都拒绝。

apply 校验原.uxprc中唯一Premiere会话，使用旧官方CLI的plugin unload --apps premierepro@<原版本>卸载该插件（不停止UXP服务或Adobe），复查未认领状态；冻结旧控制器后再核对证据，向该确切进程发送 TERM 并等待退出，不强杀、不删锁。保留旧邮箱，新邮箱用独占创建复制原字节。以新正式 bridge.py serve 读取原 scope/original/receipt-dir；只更新 controller.json、健康挑战和迁移审计记录。原 jobs/claims/receipts/permits 不改。之后执行返回的 manage.py recover-inspect 命令，重载新插件并回查原 ID。不得使用 manage start 清邮箱，不允许 submit、新 ID 或切换 PR 工程。

CLI未加载/断连等错误不会当作成功。现场已卸载时，plan可显式提供--native-unloaded-evidence；证据必须是60秒内的原生完整插件清单，绑定插件ID、原.uxprc SHA、仍存活的Premiere进程身份、观察人和可回读证据SHA，apply再次核验。历史菜单截图不能替代新鲜观察，不从错误文字推断未加载。

迁移中发现 claim/receipt、写任务或不确定执行，停止并只查原任务。终止前失败会恢复被冻结的旧控制器；终止后失败保持现场供人工回查，不自动重启旧版或清除状态。迁移回执仅证明代码/状态切换；真实 PR inspect、正确工程及后续业务需另行验收。未取得发布/生命周期动作授权时只能隔离验证。
