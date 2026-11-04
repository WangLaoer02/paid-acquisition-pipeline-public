# Seedance Skill 运行工作台 · Agent 接口 v0.4

主页面 http://127.0.0.1:8786/ 显示全部运行、实际过程和问题。查看记录不改变当前执行目标。原制作表单与画布保留在 /maker 。同一 SQLite 保存历史、步骤、问题与人工稿；CLI 不依赖网页服务。

CLI 固定入口：`python3 scripts/studio.py`。以下子命令均接在此入口之后。

## 一次真实使用

1. 用 `state`／`pending` 找到与用户目标一致的 task_id／run_id。已存在 running 记录时沿同一执行者续接；queued 记录用 `claim --run <run_id>` 领取。
2. 无使用记录时，用 `start --task <task_id> --skill <实际Skill>` 开始；多项实际方法可重复 --skill。相同开始请求重试沿 --request-key，组合使用共用一条 run。
3. `context --task <task_id> --run <run_id>` 取得该次输入与精确 Skill／参考快照。运行中的 context 读取会自动记为一步，保存 Skill 路径、SHA 与输入版本。实际采用方法与读取具体参考时，用下方 v0.4 的 read-skill 记录调用原因和上游步骤。
4. CLI／脚本工具通过 `exec --run <run_id> --title "具体步骤" -- <原命令及参数>` 执行。它自动记录开始、命令、工作目录、返回、错误和耗时，并保留原返回码；可用 --skill、--parent-step 和 --reason 关联本步的方法、来源和目的。例如：

```sh
python3 scripts/studio.py exec --run <真实run_id> --title "检查成片参数" -- ffprobe -v error -show_format -show_streams -of json <已存在视频的绝对路径>
```

5. 浏览器／原生工具等不能由 exec 调用的动作，先 `step-start --run <id> --title "实际动作" --type tool --input-json <输入JSON文件>`，执行原工具，随后 `step-finish --run <id> --step <返回的step_id> --status completed --output-file <返回记录文件>`。失败用 failed 和 --error；产物用 --evidence。步骤必须来自实际动作。
6. 阶段说明用 `note --task <id> --run <id> --summary "具体进度"`，显示在时间线。
7. 完成后用 `finish --run <id> --status completed --summary "实际完成范围" --output-file <结果文件>`；--evidence 可重复追加产物路径。发生故障用 failed，停在条件上用 blocked。结果保存在使用记录，人工稿继续保留。
8. 用 `runs` 或 context 回读。runs 返回跨任务记录、步骤、问题、文件和同任务其他运行。

CLI 默认 Agent/Codex；其他执行者在子命令前加 --actor <名称>，人工用 --kind human --actor <名称>。领取、步骤和完成使用同一身份。结束的运行不再次执行；修订开启新 run。

## 输入、历史与权限

没有相符任务时，用 `new --json <文件>`（或 --json -）创建。最小结构：

```json
{"form":{"title":"真实任务","source":"用户原稿","stop":"prompt","format":"natural"},"primary":"seedance-prompts","skills":["seedance-prompts"],"draft":"","references":[]}
```

stop 为 prompt/storyboard/handoff；format 为 natural/five/timeline。保留本次明确时长、画幅、原项目和输入。new 会创建任务并将其设为页面当前显示任务，旧任务保留；activate 可切换已存在的显示任务。真正执行仍必须使用与用户目标相符的明确task_id／run_id，不把页面当前显示当作授权。

直接更新任务需先读最新 revision，再用 `update --task <id> --revision <n> --json <完整任务JSON>`。冲突时合并或另存。使用结果通常通过 finish 返回，不覆盖当前人工稿。

exec 记录原工具的真实执行，不扩大该工具的权限、模型、账号、付费、生成或发布授权。凭据通过原授权流程传入执行进程，日志只保存业务必要参数与结果。常见凭据字段会脱敏；原任务约束继续生效。

## HTTP

JSON 写入含 actor: {kind: agent|human, name: 执行者}。服务仅绑定本机；HTTP 提供记录写入，不提供任意命令执行。

| 接口 | 用途 |
|---|---|
| GET /api/monitor | 全部运行、步骤、问题、登记文件、同任务运行 |
| GET /api/state | 当前共用任务和列表 |
| GET /api/catalog | 11 个 Skill 当前正文及直接参考 |
| GET /api/pending | 等待领取的使用请求 |
| GET /api/tasks/{id} | 任务与使用记录 |
| GET /api/tasks/{id}/context | 当前输入与 Skill；run 快照使用 CLI context --run |
| GET /api/tasks/{id}/versions/{n} | 保存版本 |
| POST /api/tasks | {actor,task} 创建 |
| PATCH /api/tasks/{id} | {actor,task,expected_revision} 更新 |
| POST /api/tasks/{id}/activate | {actor} 切换执行入口 |
| POST /api/tasks/{id}/runs | {actor,skills?,queued?,summary?,request_key?} 开始或排队 |
| POST /api/runs/{id}/claim | {actor} 领取 |
| POST /api/runs/{id}/finish | {actor,status,summary,output?,evidence?} 保存结果 |
| POST /api/runs/{id}/steps | {actor,title,kind?,inputs?} 开始步骤 |
| PATCH /api/runs/{id}/steps/{step_id} | {actor,status,output?,error?,duration_ms?,evidence?,exit_code?} 结束步骤 |
| POST /api/tasks/{id}/notes | {actor,summary,run_id?,evidence?} 进度 |
| POST /api/issues | {actor,run_id,step_id?,title,description?,position_seconds?} 标记问题 |
| PATCH /api/issues/{id} | {actor,status?,description?,comparison_run_id?} 更新或关联对照 |
| GET /api/files/{id} | 读取运行中已登记的本机文件；视频支持 Range |
| GET /api/files/{id}/frame?at=秒数 | 视频对应位置的画面 |

问题状态 open/working/resolved；运行状态保留 queued/running/completed/blocked/failed/cancelled。旧 notes 与开始／结束记录原样保留并进入时间线；新接入的 exec 与 step 事件显示工具级过程。

## v0.4：11 个 Skill 的通用排查

首页默认打开最新运行的概览：用户要求与实际结果、运行开始时的输入版本、实际登记的 Skill、调用原因、规则版本和问题。进入具体步骤看输入与返回；媒体只在关联文件或带视频位置的问题中展开。历史中只有快照、没有调用原因或读取事件时，页面如实显示缺少的记录。

### 调用、读取与结果检查

- `read-skill --run <id> --skill <实际Skill> --reason "本步为何需要这个方法"`：返回并记录该次锁定的正文。实际转专项时，可读取这 11 个中的另一个 Skill，会将它及版本加入同一 run；不修改原任务的输入快照。
- 同一命令加 `--reference <快照内的参考绝对路径>` 读取并记录具体参考，加 `--parent-step <上游step_id>` 保留调用关系。参考必须来自该次 Skill 快照；文件名不唯一时用绝对路径。
- `step-start` 现在还支持 `--skill <已登记Skill> --parent-step <上游step_id> --reason "本步目的" --expected "预期结果"`。类型为 tool/input/check/artifact/skill/reference。浏览器与原生动作沿原工具执行，再用 step-finish 保存实际返回。
- `step-finish --outcome matched|different` 保存结果检查；different 形成“输出结果”问题。工具失败、重复执行、输出文件缺失、已结束运行中的步骤无返回等由原记录提取；这些规则不替代对语义和视觉结果的检查。

### 问题与改法

`issue --json <文件>` 新建问题；同一命令加 `--id <issue_id>` 补充或更新。最小字段 run_id、title；可选 step_id、category、related_skill、expected、actual、basis、cause、fix、file_id、position_seconds。category 为 routing/input/execution/tool/output/recording，分别对应 Skill 调用、输入与参考、执行步骤、工具错误、输出结果、过程记录。保存依据和可检查的原因，不保存内部思考。已解决由人或 Agent 明确标记，不因关联下一次运行而自动解决。

```json
{"run_id":"真实run_id","step_id":"真实step_id","category":"output","title":"结果没有保留固定镜头","expected":"固定镜头","actual":"输出加入了推镜","basis":"用户原稿与本步输出","cause":"提示词加入了推镜描述","fix":"移除该描述后对照后续运行"}
```

HTTP 的步骤接口与问题接口支持以上同名字段（CLI 的 skill 对应 skill_slug，parent-step 对应 parent_step_id）。只读 `GET /api/runs/{id}/skills/{slug}` 查看本次正文和参考快照，不产生读取事件；真实执行者使用 CLI read-skill 记录调用。

对照运行显示两次用户要求、输入草稿和参考、Skill 与参考版本、执行过程、实际结果及问题状态。调用原因只是执行者当时的说明；规则正确性与最终效果应对照原要求和实际返回判断。

## v0.5：单次排查读取与导出

优先用 `inspect --run <真实run_id>` 读取某次运行；可加 `--step <step_id>`、`--issue <issue_id>` 定位。无需网页服务，返回 `seedance.inspection.v1` JSON：本次原要求、完整步骤、问题、关联文件索引，以及锁定版本的 Skill 正文和参考。读取不产生使用事件、不切换任务、不执行工具。

HTTP 对应 `GET /api/runs/{id}/inspect?step=...&issue=...`；加 `download=1` 返回 JSON 附件。同一次运行外的步骤或问题会返回 404。页面“导出本次排查”可预览、复制和下载 JSON；媒体保留原路径，没有打包进入 JSON。

问题状态筛选 open/working/resolved 与类型、Skill、时间组合使用。`runs` 仍用于跨运行发现问题，`inspect` 用于具体排查。

## 可移植运行配置

从当前seedance-prompts目录运行scripts/studio.py；完整主机配置与接续范围见 ../../references/studio.md。普通CLI context/read-skill默认仅返回参考索引；明确需要全文时在子命令前加 --include-references，inspect与HTTP排查导出保留完整快照。数据库和媒体不包含在代码包中。
