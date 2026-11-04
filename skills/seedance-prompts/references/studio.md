# Seedance 人与 Agent 共用工作台

仅在用户要求记录、从工作台排队任务续接，或当前项目已选用工作台时使用。普通提示词、舞蹈规划、买量制作、采集和字幕无需创建工作台记录。它保存输入、进度与候选，不替代原项目Sheet或采用来源。

先按已安装Skill定位 `seedance-prompts`，以下在该目录运行：

```sh
python3 scripts/studio.py --diagnose
python3 scripts/studio.py state
```

CLI 与页面共用 SQLite；页面停用时 CLI 仍可使用。实现及模块随本Skill的 `runtime/studio/` 打包，不依赖日期原型目录。完整接口见[工作台接口](../runtime/studio/AGENT.md)。

主机配置放 `~/.config/seedance-studio/config.json`，或由 `SEEDANCE_STUDIO_CONFIG` 指定；支持 `db`、`skills_root`、`media_roots`、`port`。环境变量 `SEEDANCE_STUDIO_DB`、`SEEDANCE_SKILLS_ROOT`、`SEEDANCE_STUDIO_MEDIA_ROOTS`（路径分隔符分隔）、`SEEDANCE_STUDIO_PORT` 可覆盖。未配置的新安装默认数据库在 `~/.local/share/seedance-studio/studio.sqlite3`；现有数据库丢失时配置检查会报错，不静默新建空记录。`--diagnose`只报告路径与文件存在性，不打开数据库。

可选页面用 `python3 runtime/studio/launch.py` 启动，只监听本机，默认端口8786可配置。旧服务继续保留；端口被其他版本或不同数据库占用时停止，不抢占或自动重启。只安装Skill不会启动服务。

迁移代码不迁移SQLite、原片、角色素材、参考绝对路径、登录或凭据。需要旧历史时单独核对数据库位置与媒体映射；本次不能通过新建同名任务补造历史。打包排除真实数据库、缓存和主机配置。

## 开始或续接

1. 有明确 task_id／run_id 时读取该对象；对象未知先 `state` 或 `pending`。核对用户本次目标、原稿与项目。当前活动任务只是入口，不能把无关任务的角色、素材、采用或授权带进本次工作。
2. 页面已排队：用 `claim --run <真实run_id>` 领取。没有待办但确实在使用 Skill：在相符任务下 `start --task <真实task_id> --skill <本次实际Skill>`；多项实际方法可重复 `--skill`，一次组合使用只建一条记录。续接先看已有 running 记录，沿原执行者身份继续，避免重复开始。
3. 使用 `context --task <真实task_id> --run <真实run_id>` 读取输入快照、已锁定的 Skill 正文与参考索引。按该任务停止点执行；素材路径可在本机读取，观察与平台绑定分别核实。
4. 阶段变化用 `note --task ... --run ... --summary "实际进度"`。结束用 `finish --run ... --status completed --summary "实际完成范围" --output-file <结果文本绝对路径>`；只有分析完成就如实写分析，缺条件用 `blocked`，故障用 `failed`。产物路径用 `--evidence <实际证据>` 追加。正文与证据不得含凭据或内部思考。
5. 回读同一任务，确认使用记录与候选结果已保存。Agent 输出先进入候选，不覆盖人工当前稿；需要直接更新任务时须先读最新 revision 并用 `update --revision`，冲突时保留两份并合并。

CLI 默认执行者为 Agent/Codex；其他 Agent 用全局参数 `--actor <名称>`，人工可用 `--kind human --actor <名称>`。领取与提交使用相同身份。

## 没有相符任务

准备一个 JSON 文件，使用 `new --json <绝对路径>`。至少包含：

```json
{
  "form": {"title": "本次真实任务", "source": "用户原稿与目标", "stop": "prompt"},
  "primary": "seedance-prompts",
  "skills": ["seedance-prompts"],
  "draft": "",
  "references": []
}
```

只登记本次真实需要的 Skill，保留明确时长、格式、参考和原项目。`new` 会把新任务显示到共用工作台，旧任务保留。CLI 失败时如实报告记录未写入，并将本次输入／实际结果暂存在当前任务文件；入口恢复后补记同一次使用，业务外部动作仍按原授权与防重放规则处理。

## 记录运行过程与问题

这 11 个 Skill 共用同一排查方式，按实际任务选用，不为填写记录增加生成或无关步骤：

1. `context --task <task_id> --run <run_id>` 返回本次输入与已选Skill入口，参考默认仅列路径和SHA；快照仍完整保存。实际采用某个方法时，用 `read-skill --run <run_id> --skill <实际Skill> --reason "本步为何需要它"` 读取锁定正文。转专项仍在同一 run，可加 `--parent-step <上游step_id>` 保留调用关系。
2. 具体参考通过同一 read-skill 命令加 `--reference <快照内参考路径>` 读取。仅在需要时读取对应参考；显式排查可用全局参数 `--include-references` 返回完整参考，`inspect`保留完整导出。不把快照存在等同于实际使用。
3. CLI／脚本通过 `exec --run <run_id> --title "具体步骤" -- <原命令及参数>` 保存开始、输入、返回、错误与耗时。浏览器／原生动作通过 step-start/step-finish 包住真实动作。step-start 可带 --skill、--parent-step、--reason；检查结果时用 --type check --expected "本步预期"，step-finish 用 --outcome matched/different 保存实际对照。
4. 发现问题时，用 `issue --json <文件>` 保存 run_id、title，以及需要的 step_id、category、expected、actual、basis、cause、fix。category 为 routing/input/execution/tool/output/recording（Skill 调用／输入参考／执行步骤／工具错误／输出结果／过程记录）。原因须对应具体原要求、规则或步骤；缺失过程直接指出缺哪一步。已有问题用 --id <issue_id> 更新，后续运行通过 comparison_run_id 关联对照。
5. 结束后回读 runs，确认关键步骤、实际结果与问题已保存。历史未记录的动作不补造。完整参数见工作台 AGENT.md。

## 记录含义

- queued 是等待领取；running 是执行者报告正在使用；completed 是提交了实际结果，不等于平台生成、审核通过、用户采用或商业发布。
- “整理交接稿”是页面规则操作，不伪记为 Agent 使用 Skill。
- 任务、使用记录、Skill 指纹与输入快照保存在本机；费用、生成、上传及发布沿原 Skill 与当前项目的授权边界。
