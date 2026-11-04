---
name: rongyao-ai-generator
description: 使用公司荣耀 AI 生成后台，查询模型、额度、会话、主体与任务，校验图片或视频生成计划，并通过 ryai CLI 复用现有浏览器登录提交和下载。用于 ai.cn.sy.backend.example.invalid；素材投放与 ROI 分析由其他荣耀技能处理。
---

# 荣耀 AI 生成后台

目标入口：`http://ai.cn.sy.backend.example.invalid/data/`。此后台包含聊天、图片、视频、主体库、素材库、画布与声音工具。

使用 [scripts/ryai.py](scripts/ryai.py) 查询和准备请求。Python 3.10+ 可运行本地命令；CDP 传输还需支持全局 WebSocket 的 Node.js。

```bash
python3 ~/.codex/skills/rongyao-ai-generator/scripts/ryai.py models --type video
python3 ~/.codex/skills/rongyao-ai-generator/scripts/ryai.py --output /tmp/ryai-plan.json plan \
  --type video --model bytedance_seedance_2_0_pinkuang \
  --prompt '白色摄影棚里红色立方体缓慢旋转，固定镜头' \
  --video-mode full --duration 5 --resolution 720p --ratio 16:9 --no-audio
```

## 登录复用

账号复用、机器差异与撤销统一按已安装的 `rongyao-keyring` Skill；本节只定义AI独立会话与传输，不用HTTP查询或上传状态代替AI受保护读取。

默认 `--transport auto` 从本机专用会话状态发现当前端口与唯一AI标签页；缺少有效目标时交给固定钥匙包 `ensure-ai`。不依赖普通Chrome扩展或前台焦点，不复制Cookie、不修改浏览器安全设置；只有原专用进程确实退出时才按原配置恢复。

- `--transport browser` 为显式兼容模式，仅适用于非提交的脚本准备：生成待运行的同源请求脚本。加 `--script-out /tmp/ryai-quota.js` 保存脚本，再通过 CUA 在已登录页面运行；结果下载为 JSON。`prepared` 表示只准备了脚本，未发送请求。遇控制台安全警告交给用户处理，不能自行输入 `allow pasting` 或换方式绕过。
- `--transport cdp --cdp-url http://127.0.0.1:PORT`：仅连接已经启用调试的现有浏览器和目标页面。多张 AI 标签页需指定 `--target-id`。没有可用会话就返回错误，不启动或重启浏览器。
- 普通 HTTP 请求可能被重定向到 `power.houtai.backend.example.invalid/?_c=login`；这不证明现有 Chrome 未登录。
- 缺少登录/连接信息时，先按项目 AGENTS.md 查询 access directory。目录条目不是凭据授权。不要把凭据带到聊天、技能或日志。

## 操作顺序与参数

本机用户的视频输出默认720p；在模型支持时，计划显式传`--resolution 720p`并回读生成参数。用户当次明确指定的分辨率优先；输入动作参考保留原生清晰度，不能以放大低清参考充当高清来源。

查询 `quota` 和 `models`，用 `plan` 形成可审阅的请求。`models` 读取 2026-10-05 已登录页面的配置快照，明确标记 `live=false`；模型变化时用 `refresh-models` 在现有页面导出，再核对快照。

Seedance 自接 API、七牛、拼框、Mini 拼框具有不同模型键和限制。保留完整模型键，不能因显示名称接近而换渠道。详细接口、参数和命令见 [references/backend-contract.md](references/backend-contract.md)。

上传参考或实际生成按用户请求授权范围执行。`upload` 和 `submit` 默认只做预览；`--execute` 才生成执行请求。学会使用、封装 CLI 或整理格式本身不授权付费生成。CLI 不会自动重试提交；未知结果先查原会话或 task_id，避免重复扣费。

附件使用 `upload` 返回的完整素材对象，不能把本地路径或文件名当 attachment_id。主体通过 `subjects --keyword` 读取，使用真实 `subject_refs`；只有提示词写 `@名称` 不保证绑定成功。首尾帧按首、尾顺序提供两张已上传图片。续接会话明确给 chatid 和 parent_ids，避免串入无关上下文；默认新会话。

## 结果判断

`task --task-id` 查询原任务。后台终态为 `done / failed / timeout / cancelled / canceled`。只读轮询可继续，提交失败/未知不自动重放。

`inspect` 区分任务完成与素材数量；`download` 仅请求下载；`verify-download` 对真实落盘文件计算 SHA256，并在 ffprobe 可用时读取媒体流。媒体元数据校验不代表播放、同版本比对或美术验收。素材与历史消息有分页，保留 `has_more` 和游标，不把首批数据写成全量。

声音克隆、TTS、主体写入、收藏、删除、视频超分和 AI 画布属于独立操作。当前 CLI 提供声音历史查询，其他操作先按对应界面和契约准备；不因普通图片/视频请求顺带执行。

## 管线生成固定入口（WF20261016.1）

在当前已发布工作区使用 `python3 scripts/ryai.py`。全局同源CLI在实际提交前核对源码与正式wrapper SHA，并一次性转交工作区固定入口；不放宽writer或票据守卫。帮助和非法参数只做本地解析，不访问钥匙串或登录。

`inspect-plan --plan <绝对路径>`只读返回完整计划input_sha256与scope `paid-generation:rongyao-ai-generator`。付费提交需同时提供 `submit --plan ... --execute --workspace ... --authorization-ticket ...`；票据action为paid_generation，必须绑定本次输入。runtime在发送点校验当前发布、指定主机、依赖、scope锁及单次授权。用户已明确要求本机生成；当前action_writer_hosts允许本机paid_generation及material_upload。每批仍需当前输入SHA单次票据，状态回写与商业发布不随之授权。

计划计价为null时拒绝默认提交。只有本次明确授权未知计价例外，才加`--allow-unpriced`；这不是免费，也不扩大项目总额度。按真实计量单位记录已结算、未结算预留和本次费用上限。

作业在发送前持久化submission_pending，返回task/chat/request ID后记submitted；断连或无法确认结果记submission_unknown。同一完整输入SHA已有记录时禁止再次发送，用`job-status --input-sha256 ...`读原记录，再`task --task-id ...`回查。认证失败发生在发送检查点之前，不冒充已提交。既有历史任务缺少新账本时仍沿原task查询，不以重新提交补登记。

默认auto只复用原专用会话。明确拒绝、验证码或安全警告保留现场，不更换浏览器、账号或接口；pending登录的单次提交检查点跨调用保留，优先确认原门户是否已经登录。

## 已登录网页的受控原生提交（WF20261029.5）

用户明确要求修复路径且已验证普通Chrome登录时，可使用工作区固定入口的`native-submit`管理一次CUA原生发送；不复制Cookie、不重试原pending密码、不绕过验证码或拒绝。默认auto认证路径保持不变。

计划使用`rongyao-native-ui-v1`，包含已校验的generation_plan、真实本地参考文件SHA、完整可见页面回读SHA、参数和费用证据；原生附件不伪造API attachment_id。预检不提交。执行必须绑定当前输入SHA短期票据和项目总预算账本；固定CLI持有同一scope互斥锁，保存submission_pending并预留费用后才输出READY_FOR_ONE_NATIVE_SEND。操作者随后以CUA再次核对当前网页并只点击一次发送，在90秒内回传可追溯的页面受理证据。EOF、超时、错误保留submission_unknown与费用预留，不自动重发或退款。实际扣费另行回读；只有任务返回才能称受理，素材下载验收仍独立。

此路径仍校验发布SHA、writer、依赖、锁、票据与预算。不把页面登录等同于auto连接修复；安全拒绝不能以此路径回退。
