# 命名、参数与回执映射

归属当前同版backend-upload 1.2；以下固定字典/协议只对应原14条Plan旧接口，不是通用CLI默认字段或凭据前置。普通上传读rongyao-operations最短路径，缺实际字段才查询枚举。执行字典 `workflow/maintenance/upload-acceptance/config/requester-ai-rules.json` 由发布清单校验；本表只覆盖现有适配范围。

| 输入／命名 | 后台参数 | 已核映射与检查 | 回执 |
| --- | --- | --- | --- |
| YYMMDD | name内日期 | 真实制作日，偏差只提醒 | 日期提醒 |
| 制作人代码＋序号 | name及getVideoNames | 原生编号预检，不推断账号 | 名称／冲突 |
| 内容描述 | name及filename_tag | 按原页面算法拼标签；源帧识别只提候选 | 素材名称 |
| 倒数第二段需求人代码 | demand_name | JZY→示例人员3，DY→示例人员4；value为姓名 | 提交值与详情分别标 |
| 主设计师 | provenance.designer_name 或 source_native_fields[设计师] | 使用原详情/用户明确归属，与需求人、第二设计师分别核验；不从尾码猜，不伪造 designer 表单参数 | 原 ID 的主设计师读回 |
| 独立AI标记／明确AI需求／已核AI分类 | ai_source | SD2拼框；非AI空；实时选项须存在 | 提交AI／详情AI |
| 后台项目分类 | category_type | 火影117，其他待真实字典 | 分类，与生产项目分列 |
| 一类 | source_type[] | 剪辑、小剧场、口播 | 列表回查 |
| 二类 | source_direction[] | 对应竞品、AI、攻略 | 列表回查 |
| 角色 | tag | 宇智波鼬、佐助、带土、卡卡西；逗号组合 | 提交与详情分列 |
| 固定业务 | origin_type / is_redbag / region_type | 1 / 0 / 空，变化停 | 固定值 |
| 实际登录 | create_name及私有字段 | 显示名核对，数字UID未知 | 不从人员码／素材ID猜UID |
| 文件字节＋目标 | request_key / time nonce | 同文件／同名受理去重 | 未知不重传 |
| 入库响应 | 素材ID、列表和详情 | 名称／分类／一二类回查，其他另审 | 成功／跳过／失败／待确认 |

公司页面实测协议，不宣称官方公开API：表单 `http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video`；同路径预检 `ac=getVideoNames`、回查 `ac=jrttVideoList`。分片／合并在 `http://cdnapk.backend.example.invalid/api/controller/ApiUploadVideo.php?act=upload`／`act=join`，20MiB。name、total、index、time及完整join字段沿已验源码，禁止复用AI生成接口。

## 方向标签（类型）默认忽略

后台“类型”字段会把竖版成片误标为横版，属平台侧显示异常。以实际文件尺寸和音视频解码为准（成片 720×1280 即竖版），不回读改写、不重传、不阻断入库，只在回执里留一条异常记录。

## 主设计师归属与原 ID 收尾

计划保存主设计师来源于 provenance，不是新增 `parameters.designer`；实际表单不提供该键。`create_name` 保留真实登录身份。原素材已有“设计师”时继承其明确姓名；需求人或首段/末尾代码不能代替原归属。

已入库后用 HTTP 执行器 `finalize-attribution --job-id <原job> --workspace <原工作区> --authorization-ticket <归属收尾单次票据>`，沿实际详情页的 saveDesignName 动作修改原 ID。既有上传授权涵盖正确归属；仍须原 runtime 单次票据和原计划 SHA，不重传、不换 ID。reconcile 保持只读并支持 --refresh-details。

验收必须逐项包含主设计师、第二设计师、需求人及其他可见业务字段；详情读取成功和入库成功不能替代字段正确。未知变更受理只读回查，不重放 POST。完整命令与字段证据见 rongyao-http-upload 1.2.0。

依赖源码在同版规则包 `implementation/backend-upload/workspace/`。Skill内是只读入口，实际提交调用已部署工作区；新机器先部署、核验依赖，不把历史Plan当通用接口。输入、身份、目标未知或工具访问拒绝时停，不能换surface绕过。

## 原14条固定Plan：提交及回查


本节不是普通上传前置条件，不因新文件缺该Plan或私有请求文件而阻塞通用CLI。缺既有安全输入只报告旧接口能力缺项，不重复索取登录授权，不主动索取/迁移Cookie，不切通道绕过拒绝。

先运行 `python3 scripts/entry.py check --workspace <工作区>` 核对Skill、脚本、配置、节点图及中心同版，再人工核对真实账号、该批上传授权、已审输入和映射。沿现有无浏览器“视频列表→新增视频”接口，见 mapping.md。认证只从用户安全提供的一次性私有请求文件消费后删除，本批内存复用；不在聊天、文档、回执或日志输出密码、Cookie、Token。缺安全输入则保持依赖，不复制浏览器配置或换账号。

条件齐全才启动工作区 `python3 scripts/rongyao_fast_session.py --request-file <一次性私有文件> --display-name <真实登录显示名> --authorization-ticket <原接口对应票据>`。stdin每行JSON：`{"action":"run","name":"已验Plan中的唯一完整文件名"}`，或 `{"action":"batch","names":["已验文件名"]}`；结束 `{"action":"quit"}`。请求文件格式沿 `rongyao_checked_upload.py` 安全接入合同，不把公开业务JSON当凭据。未知名字不得提交。

复用已验媒体检查；发送前只读取一次实际字节，比对长度及SHA，改变则停。每批一次表单与原生命名预检，最多4条同一登录态并行；20MiB分片与完整join参数，合并受理后释放发送线程，再统一有限回查。账本锁只覆盖占用及写回，避免每条重复全片解码、抽帧、菜单探索、凭据接入、无关测试与维护写回。

请求键关联入口、文件SHA、名称及目标参数，nonce持久留证。同文件／同名已有记录只回查；受理未知或发送中禁止改nonce、删账本、换参数或新登录态自动重传。明确拒绝的重试也须核对旧终态及本次具体授权。每命令59秒截止留反馈时间；未证实入库只报待确认。四线程是同账号素材并发，数字登录UID和真实多登录态并行待验，不能混同需求人代码或素材ID。


## 原14条固定Plan：完整反馈要求


HTTP200、上传响应或join受理只算运输／受理证据。通用CLI完整名称唯一匹配真实ID可记入库；元数据全参数验收单独记录。以下旧接口完整反馈要求仅适用明确续接原Plan。新增成功必须有真实素材ID、名称、项目分类、一类及二类回查；角色、需求人、AI和方向还须独立详情核对，缺项不称全参数验收。已存在同名跳过不计新增，不证明与本地同SHA。

固定批反馈：新增成功数、同名跳过数、冲突／失败数、待确认数；逐条生产项目名、后台分类名、一类、类标签、需求人代码／姓名、AI、素材名／ID、耗时、日期提醒、回执路径。角色提交值与详情值分列。适配器“项目名称”实际来自category，不能冒认生产项目。未回查条目成功数0，未知仅继续只读回查。

状态／报告入口 `python3 scripts/entry.py status --workspace <工作区>`：只读公开脱敏回执，显示最近时间、状态计数、输出位置与阻塞项，不读私有凭据，不把旧成绩当本轮结果。`--offline-preparation`仅明确非付费准备，不能提交。

逐轮实测耗时、ID、详情差异与采用留 evidence 和独立维护文档。现有真实入库样本与本地去重／并行／截止测试不等于新策略实网通过；稳定一分钟入库、通用CLI其他批次逐批验收，详情／播放、真实多登录态并行仍待验。反馈截止与实际入库耗时分别核验。

## 原14条Plan固定字段字典


以下固定值属于原14条Plan接口；新CLI按本次项目实际字段和完整页面枚举，不把旧AI、第二设计师和命名案例强加给新文件。

需求人取倒数第二段，最后段是设计师代码。已确认 JZY→示例人员3、DY→示例人员4；`demand_name`为真实后台姓名value，数字ID未知不得猜测。未知缩写、页面缺选项或字典变化停该条，报告缺失映射。

名称含独立AI标记、用户明确确认AI需求或已核AI分类时，`ai_source`取 `SD2拼框`；非AI为空，不把普通单词内ai误判为AI。火影→117；本版已验一类／二类为剪辑／竞品、小剧场／AI、口播／攻略；角色提交值限宇智波鼬、佐助、带土、卡卡西。其他项目、角色或类型先补真实字典。固定 origin_type=1、is_redbag=0、region_type为空，逐批核对表单；提交值与详情落库值分别记录。

