# 给接收方Codex：渐进安装与实现验收

## 开始：两份下载，安装与案例分开

飞书手册： https://example.invalid/receiver-feishu-document

1. 下载手册当前同版安装包，按文档公布的SHA256核对整包后解压。
2. 仅复现首例时另下载V002案例包（362,920,772字节，SHA256 `3793a71dea43d20fc51315af87a48391b30253277691281601a7625e547df51e`）： https://example.invalid/receiver-feishu-document
3. 不要把这两份包解压覆盖到原项目、现工程或现Skill目录。安装器接收一个解压后的安装Skill目录。

安装包要求Python 3.10+。它包含真实Skill源码ZIP、完整当前规则和实施脚本；模型、许可软件、登录态及Codex连接器是接收机器的独立依赖。复制Skill不能制造MCP工具。

把以下任务交给另一个Codex，补上解压位置：

```text
按这份飞书手册配置买量短剧工作流。安装包已解压到「实际路径」。
先读取paid-skit-progressive-setup/SKILL.md和references/progressive-setup.md的开始章节。
只处理bootstrap与当前制作阶段：verify → plan → 安装获准的本机文件/隔离依赖 → doctor。
源目录冲突保留我的原文件；不要一次展开或安装全部下游。
需要登录、连接器、审美或生成费用时，先查当前项目与可用授权，再仅补对应缺项。
安装不包含付费生成或发布授权，不借用示例账号、项目、预算或会话。
我先复现SK002已有成片时，只准备阶段6/7，校验/重连案例包，再实际PR原生打开和导出。
```

进入安装包目录后，以下命令中`python3`应替换为目标机已核对的Python解释器；Windows可使用实际`python`路径。

```bash
python3 scripts/progressive_install.py verify
python3 scripts/progressive_install.py plan --phase bootstrap
python3 scripts/progressive_install.py install --phase bootstrap
python3 scripts/progressive_install.py doctor --phase bootstrap
```

默认Skill目录：`$CODEX_HOME/skills`，未设置时`~/.codex/skills`；工具目录：`~/.local/share/codex-tools/paid-skit`。用全局参数`--skills-dir "目标目录" --tool-root "目标工具目录"`放在子命令前可改位置。不改HOME/CODEX_HOME，不改其他机器配置。新Skill可在Codex下一轮发现；必要时显式给出已安装SKILL.md路径。

安装器只给当前phase写文件，安装记录是`tool-root/installation-state.json`，不代替项目表、制作检查点或授权账本。`plan/doctor/verify/path`不写环境或业务；`install`只复制Skill；`env-install`联网装隔离Python依赖；`tool-install-feishu`联网装隔离npm工具。

## 每个阶段的实际步骤

通用顺序：`plan --phase N → install --phase N → doctor --phase N → 核对manual_gates`。`doctor`退出2表示软件/文件仍缺；即使退出0，账号、当前规则及原生验收仍以实际证据为准。

### 阶段0：项目与飞书底座

安装主Skill及lark-shared/doc/drive/sheets。先检查现有CLI与原身份；不要因文档中的示例而新建项目表。

```bash
python3 scripts/progressive_install.py plan --phase 0
python3 scripts/progressive_install.py install --phase 0
python3 scripts/progressive_install.py tool-install-feishu
python3 scripts/progressive_install.py doctor --phase 0
```

已有lark-cli时安装器保留它，需实测`--version`与文档所用shortcut。没有时从官方npm包固定安装1.0.93到tool-root/npm，不全局覆盖；输出实际二进制路径。后续所有`lark-cli`命令用该路径运行，或仅为当前终端配置该目录PATH。

读取已安装lark-shared。无配置时按其config-init参考启动交互配置；无登录时按身份参考执行`auth login --recommend`。授权URL原样展示并生成二维码。已有登录用接收者自己身份核对，不能复制原作者Cookie、Token或账号文件。遇授权缺项先查目标机器已有连接/metadata-only访问目录，凭据目录不是授权。

飞书规则读取使用接收Codex已配置且有权限的飞书连接器；无该工具可先从已核对的完整快照学习/离线复现，准备正式新项目前确认当前规则版本。账号、来源、预算和停止位置写到本项目唯一Sheet。

### 阶段1：原片、元数据与声音

安装完整douyin-video（含原先漏带的extract_bgm.py及recipe）。先准备FFmpeg/ffprobe，再按需要装media环境。实例命令先用`path`取得真实脚本位置，不照抄原Skill的~/.agents路径。

```bash
python3 scripts/progressive_install.py install --phase 1
python3 scripts/progressive_install.py env-install --profile media
python3 scripts/progressive_install.py path --skill douyin-video --file scripts/douyin_downloader.py
python3 scripts/progressive_install.py doctor --phase 1
```

用media环境的Python运行返回脚本：`--link "本项目分享链接" --action download --output "本项目源片目录"`。元数据/同版音乐走真实extract_bgm.py；按其recipe读取准确用法。不可取得原片时停在来源缺项，不用简介当转写。

原fast_transcribe.py需要本机快速服务、whisper.cpp或whisper CLI之一；复制该脚本不意味着接收机已有服务。包内新移植适配器`transcribe_local.py`使用与实施环境相同的faster-whisper，FFmpeg解码数组、CPU/int8、精确本地模型；不自动下载权重。

仅缺快速服务且确需本地转写时：`env-install --profile speech`，按faster-whisper官方文档准备并校验模型snapshot，再运行以下命令，输出是机器核对候选，仍需看画面与回听。

```bash
"实际speech环境Python" scripts/transcribe_local.py "实际源片.mp4" --model-dir "已核验的本地模型目录" --output "新的核对稿.json"
```

模型首次下载需独立明确命令及接收者认可的来源/网络与磁盘范围；本安装器没有下载模型命令。不下载已完整缓存的权重。只有需要对已核对文字进行中文对齐时再安装`align`环境，WhisperX不放阶段0。不同OS/CPU若锁版本不可安装，保留失败事实再验证兼容版本，不静默升级。

### 阶段2：剧本与分镜

安装`paid-skit-copywriting`与`paid-skit-storyboard`，进入时读其完整canonical.md和source.json。两份是实时飞书原文的安装适配，没有把口吻或检验规则改成摘要。确认原片因果、情绪与时长后再下游。

### 阶段3：母版、状态图与必要入库

安装三视图、资产桥、角色格式和imagegen入口；进入哪个子环节再读对应规则。需要图像检查时`env-install --profile vision`。imagegen原生工具来自目标Codex的现有能力；未暴露时停止该能力点，不能靠Skill复制假装安装好。API CLI模式仅在用户明确选择该模式后单独配置与计费。

进入角色库才读资产桥和格式；一致性、脸参、队列三个原脚本已收录在格式Skill/scripts。按当前契约提供输入；固定历史项目的compile执行器未分发；仅保留来源记录，需按当前契约参数化并验证后才能用于新项目。新输出使用 DIRECTOR-STORYBOARD-1 分镜导演稿，按逐镜命名槽位写入；既有项目先核对其登记模板，不恢复旧管理区，不另建资产或状态主表。

### 阶段4/5：正文、绑定与生成CLI

默认按首例荣耀路线安装当前视频提示词适配器与真实ryai完整源码：

```bash
python3 scripts/progressive_install.py install --phase 4 --backend rongyao
python3 scripts/progressive_install.py path --skill rongyao-ai-generator --file scripts/ryai.py
python3 scripts/progressive_install.py doctor --phase 4 --backend rongyao
```

Python3.10+可做本地models/plan/help；默认auto发现原专用会话的当前port/target，由固定钥匙包恢复并核验AI保护接口，Node22+提供WebSocket。browser仅为显式脚本准备兼容模式，prepared不等于发送。付费提交走同版工作区scripts/ryai.py，绑定paid_generation票据和完整计划SHA；未知计价须当次例外，未知受理只查原任务。help不认证，pending不重复登录，安全拒绝保留现场。

需要即梦路线才指定`--backend dreamina`安装真实dreamina-canvas-cli。二进制由owner当前发行来源提供，本包不包含那份Mac编译程序；目标机先验实际版本/schema、账号，再引用上传/报价。两条路线不混用资源ID或费用单位。

在用户费用授权内执行实际 `上传回读 → plan → 正文/绑定/参数/报价预检 → submit --execute一次 → task/session查原任务 → download → verify-download`。安装过程中不运行其中的上传、submit或其他业务写入。阶段5同样指定本项目backend，未知任务不重复提交。

### 阶段6/7：可编辑工程与原生导出

仅复现首例，可直接从bootstrap跳到此处，不安装阶段1—5或模型。

```bash
python3 scripts/progressive_install.py install --phase 6
python3 scripts/progressive_install.py env-install --profile premiere
python3 scripts/progressive_install.py doctor --phase 6
python3 scripts/progressive_install.py install --phase 7
```

案例包解压后用其`复现.py verify`和`relink`，再打开新生成本机重连工程。准备有许可的PR、思源黑体真实Bold；按飞书手册的两版片段开关与Out导出，不按文件名猜范围。

新项目读取当前工程，以py-premiere 0.1.0最小修改并回读。包内pr_inspect.py只读真实路径，不认证原生打开。历史README及锁文件保留来源；固定SK001的旧重建器未作为当前执行器安装。

完整观看与声音、PR原生打开/保存/导出、其他机器体验分别验收。只有实际导出文件且解码/音画通过才标对应制作状态；发布另授权。

## 冲突、恢复与完成

同名Skill必须先全阶段比对。差异即拒绝本阶段所有新写入，已有目录、符号链接和手改保留；先判当前来源/版本，再由用户授权最小迁移，不能删目录重装。重复安装相同版本跳过，不会重置源文件。环境安装失败保留隔离目录，仍用同锁文件续接；不标软件可用。缺可选实现按source-and-conditions停止该分支，不停独立可用准备。

安装验收包至少包含：安装包SHA、Python/OS/arch、源文件校验、实际安装目录、各phase结果、环境导入、CLI版本、账号/工具能力待验及下一项。安装器实测不代表原生PR/业务接口验收。生产继续用项目表首个未完成阶段，不用安装事件替代。

若pip报证书链错误，保持失败/未就绪，先核对目标机受信任证书配置。可将owner认可的系统/组织CA用`env-install --profile NAME --ca-bundle "实际CA文件"`传给这一次pip；不改系统证书、不关闭TLS验证、不使用trusted-host。路径不存在即拒绝。网络失败不能据此判断包版本不存在，保留同一隔离目录与锁续接。

权威安装与接口来源：[官方飞书CLI](https://github.com/larksuite/cli)、[py-premiere](https://github.com/Pouf/py-premiere)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[FFmpeg](https://ffmpeg.org/download.html)、[Node](https://nodejs.org/en/download)、[思源黑体](https://github.com/adobe-fonts/source-han-sans)。

## 安全续接与清理版本

V003来源及逐文件调整见references/curation.json。环境目录或状态文件为符号链接时拒绝执行，保留链接目标。遇到CERTIFICATE_VERIFY_FAILED时保持原环境，仅在已确定受信任CA路径后重试：

```sh
python3 scripts/progressive_install.py env-install --profile premiere --ca-bundle /absolute/path/to/trusted-ca.pem
```

不关闭TLS校验，不把网络证书失败误判为包不存在。其他profile同样支持该参数。


## 后台素材上传安装分支

当前同版WF20261103.1／V005.38。`--phase upload`安装rongyao-material-upload及荣耀工具9个同源Skill，属于原A15／接B05之后的独立专项，不是生产单选新节点。仅首次部署/版本或环境变化时核对工作区与Skill；普通上传已就绪时直接读rongyao-http-upload提交与恢复合同，不重复Skill check、入口探测或登录授权；需要独立Python环境时使用`env-install --profile upload`，仍不登录或上传。Skill安装不带项目Plan、媒体或凭据，缺已审输入保持阻塞；具体提交范围和未验证能力读Skill全文。

上传分支包含rongyao 0.2.3同源实现；通用计划经workspace／输入SHA票据、writer与scope保护。沿当前专项区分通用CLI和原固定Plan，真实新批次上传另验；不复制账号、状态或媒体。
