# 买量短剧主控路由

当前发布由飞书中心WF_RELEASE_JSON核验。不要通读规则中心、历史手册、全部模块或全部项目。

1. 已知真实item直接context；只有对象未知时才运行 `python3 scripts/workflow_node.py list`，从当前任务指定项目匹配唯一item_id，多个版本不能按名称猜测。
2. 执行或续接：`python3 scripts/workflow_node.py context --item <真实item_id> --format json`。一次完成同版检查、该对象及其真实依赖节点读取，返回当前节点的合同、共用硬规则和必要正文，不写业务数据。
3. 只读取返回的当前节点正文；额外分支符合触发条件时追加 `--condition <分支>`。需要确认一条规则时用 `lookup --policy <真实policy_id>`，禁止为查一项全文搜索所有历史。
4. 按合同read→deliver→gate执行。确定性脚本沿当前工具合同；版本／节点／用户采用和费用分别核对。写回只用console_content命名槽位与原状态同步保护。
5. 恢复仍用同一item的context；该次已含状态与依赖，不另跑status。仅单独查询状态时才用status；节点前移不等于PASS，不重复既有制品或提交。

离线检视仅用 `context --node A05 --offline-preparation`，只用于本地模板／非付费准备，不能据此认定在线状态或准许提交。完整24节点由stages目录及node_skills.json定义。工具不会代替生成、审美、授权或商业发布。

正文完整保存在按需片段与policy-index；archive只为溯源、恢复和明确历史复现。所有跨节点硬约束在shared/guards.md。旧全文读取指令由本路由替代，不删其业务要求。

- `main.88`｜创作模式与最新采用来源 → `fragments/main-88.md`

## 按当前单选节点接续后台素材上传（WF20261024.1）

真实A15／B05归档且实际文件、内容验收及本批上传授权齐全后，按条件加载backend-upload.07至.12。独立成片上传委托按该文件和授权核验，不替项目完成制作、不推进原24节点。当前计划与账本入口为`python3 scripts/rongyao.py`（0.2.3），默认提交与恢复读取同版`rongyao-http-upload`（1.3.1）；必须匹配同版工作区、指定writer、scope锁与完整登记计划input_sha256的单次票据；保留原固定Plan接口。历史片段backend-upload.01至.06及main.87只保留来源追溯，不作为当前上传入口。

本版已完成通用CLI接入与隔离回归；真实新视频提交、详情、远端播放和入库时延仍按具体新批次验收。历史已listed跳过，选文件后受理未知只回查，不因换票据重传。真实多登录态并行仍待验。维护问题与项目业务状态分别留在既有入口。

- `main.91`｜后期交付准备 → `fragments/main-91.md`

- `main.90`｜交付完整性、字段语义与返工版本 → `fragments/main-90.md`

## 荣耀CLI稳定执行（WF20261017.2）
当前工作区`scripts/ryai.py`负责生成准备、自动会话连接、受paid_generation守卫的单次发送及原任务回查；`scripts/rongyao.py`负责计划、账本与显式Chrome兼容分支；默认提交和回查按同版HTTP合同。先验证动作主机与发布，生成依赖包括真实ryai、Node、固定钥匙包和保护接口。全局同源CLI仅在SHA一致时转交已发布wrapper。CLI连接或pending登录问题先诊断对应层，不切换到用户前台浏览器来代替修复；明确人工门保留现场。
