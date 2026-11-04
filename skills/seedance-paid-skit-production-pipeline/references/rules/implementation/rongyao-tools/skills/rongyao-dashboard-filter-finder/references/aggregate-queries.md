# 专项汇总与数量查询

仅在月度总计、跨项目、素材编号、原创素材或特殊筛选需要保留原汇总口径时读取。普通火影素材CSV导出和表现分析走主Skill统一入口，不先运行本文件的查询。这里的“素材产出数量”是新素材2.0投放样本计数，不可代替视频列表的生产台账。

月消耗按自然月逐月查询 gid=193、date_group=tenyear，从总计花费读取；不以明细求和代替。先读 monthly-spend-capture.md；浏览器手动路径才读 fast-monthly-capture.md。产出数量读 material-output-capture.md；编号/原创素材读 high-cost-material-query.md。上述文件均在本Skill references 目录。

这些现有汇总脚本仍使用原Chrome查询桥；HTTP素材CSV适配器不支持它们的全部项目和维度。提交前选定入口，不因失败跨通道重放。所有查询共用主Skill的日期、证据、授权和停止规则。

## 素材产出数量核心口径

1. 不按目标月份筛选 `素材产出日期(date2)`；保留本次确认的完整产出范围，用 --material-range 显式传入。
2. 只把 `日期(date)` 设为目标自然月首日至末日，不延后结束日。
3. 默认把 `否定词(negative_keyword)` 留空，不排除 XG；保持 `类型=视频(source_video_type=1)`、`数据维度=新注册(record_type=3)`、`过滤数据=是(filter=1)`。
4. 按用户项目选择母游戏及其全部动态标签/子游戏；咒术必须把 `新咒术师(197)` 与 `最强咒术师(192)` 放进同一次查询。
5. 使用 `区间汇总2(date_group=tenyear)`、`素材维度(group=mid)`，读取结果区 `总数量`；响应等价字段为 `info.sum.count`。不得读取分页行数或 `总计→花费`。
6. 优先运行 `scripts/capture_material_output.py --material-range "$resolved_material_range"` 通过已登录后台接口并发抓取，不进行浏览器逐格操作。

## 高成本素材明细保护

1. `group=material_serial_number` 会在每个编号行内嵌完整素材明细，属于高成本查询；禁止并发分页、禁止逐编号并发搜索、禁止多个脚本实例同时运行。
2. 每个日期区间只允许一次 `search[submit]=1`。取得 `info.rand` 后，后续页只修改 `page`、复用 `rand_num=info.rand`，不得再次提交整张报表。
3. 首页配置或首次重查询出现超时/504 时立即熔断本批，不自动连续重试；报告 `backend_unhealthy`，等待服务恢复后再由用户重新运行。
4. 后台助手把网络错误转换为 `SystemExit`；脚本必须显式捕获并转换为受控失败，不能只写 `except Exception`。
5. 原创素材计数使用 `scripts/capture_original_materials.py --material-range "$resolved_material_range"`；脚本通过单实例锁、单并发、会话分页和状态报告执行，不得临时改写成并发请求。

```bash
python3 scripts/capture_material_output.py --material-range "$resolved_material_range" \
  --start-month "$resolved_start_month" --end-month "$resolved_end_month" \
  --project 火影 --project 咒术 --project 烈焰
```

## 快速执行

参数完整时直接运行确定性入口，不做 `ls/find`、`--help`、源码扫描、重复 `status` 或浏览器翻页：

以下变量由前述请求契约解析得到，不是用户必须手填的新增字段：`resolved_material_range`格式为`YYYY/MM/DD-YYYY/MM/DD`，月份为`YYYY-MM`，投放日期为`YYYY-MM-DD`。素材范围优先用户范围，其次当前配置，兼容默认及缺口规则见 `rongyao-data-stack/references/capture-habits.md`。先确认变量已解析再执行，不把历史示例日期当实际筛选。

```bash
python3 scripts/capture_monthly_spend.py --material-range "$resolved_material_range" --start-month "$resolved_start_month" --end-month "$resolved_end_month" --capture
python3 scripts/capture_material_output.py --material-range "$resolved_material_range" --start-month "$resolved_start_month" --end-month "$resolved_end_month" --project 火影 --project 咒术 --project 烈焰
python3 scripts/capture_original_materials.py --material-range "$resolved_material_range" --start-date "$resolved_start_date" --end-date "$resolved_end_date" --project 火影 --code ZX
```

以下兼容汇总入口都复用 `rongyao-data-stack/scripts/readonly_capture.py`：复用专用Chrome活动会话；专用进程确实退出才恢复同一配置，连接状态未知则停止。磁盘Cookie仅为显式direct兼容选项，不作活动会话失败的自动回退。登录决策按已安装的rongyao-keyring。普通汇总使用有界批量；素材编号自动强制单实例和串行分页。输出带 `transport`、各项 `elapsed_ms`、批次 `cache` 与导出预检证据。

1. 先使用 `rongyao-dashboard-filter-finder/references/export-and-filter-map.md` 的稳定字段地图；首月只做一次完整口径核验，禁止每月重新扫描整页。
2. 读取当前控件值，只修改与请求契约不同的字段。`gid=193` 且依赖选项已加载时，不重复打开母游戏或超长多选。
3. 优先直接填写日期面板的开始、结束输入框；只有输入框不可用时才点击日历日期，且每次打开后重新识别左右月份，不沿用坐标推断。
4. 按依赖顺序批量设置：`gid → category/pkid`，`operation_client → pcid → accountId`，再设置其他独立字段。
5. 所有筛选设置完后只点击一次“查询”；不要每改一个控件就查询。按月批量任务在同一已登录标签页循环 `改日期 → 查询 → 读总计`。
6. 查询前记录当前 `search[rand_num]` 或等价 `rand`；查询后等待会话值改变，再只读取目标日期、`总计→花费` 和总条数。不要靠连续完整页面扫描等待刷新。
7. 查询提交后的控制连接只尝试一次结果读取恢复；仍超时则停止，不改用其他通道重发查询。
8. 导出按钮复用最近一次成功查询返回的 `rand` 会话；改了筛选但没重新查询时禁止导出。
9. 素材编号/原创素材任务不得套用月消耗的并发策略；先判断响应成本，再按 `rongyao-dashboard-filter-finder/references/high-cost-material-query.md` 执行。
