# 数据身份确认

日期示例仅说明格式；实时操作必须传 --material-range 指定当前已确认的完整产出范围。历史控制值不随包迁移，没有本次校准输入时 calibration.passed=null。

## 读取数字前的确认顺序

1. `project_alias`：用户称呼，例如 `火影`。
2. `project_field`：后台筛选字段；火影月消耗使用 `母游戏`。
3. `project_value`：`忍界大战(193)`，稳定标识 `gid=193`。
4. `dataset`：荣耀后台 `adopenplatformSource` 已登录页面的实时查询结果。
5. `grain`：`calendar_month`，每个月必须独立查询。
6. `period`：`Asia/Shanghai` 下自然月首日至末日。
7. `aggregation_method`：`interval_total`；界面为 `区间汇总2`，后台值 `date_group=tenyear`。
8. `filter_fingerprint`：除项目和日期外，核验类型、数据维度、过滤状态、系统、标签及其他会影响结果的条件。
9. `metric`：`spend`；读取 `总计` 行 `花费` 列，单位 CNY。
10. `freshness`：记录本次观察时间；不得把筛选日期当作更新时间。

## 生效状态判定

- 日期控件收起后，页面日期值必须精确等于目标自然月范围。
- 母游戏控件必须显示 `忍界大战(193)`，底层值必须为 `193`。
- 日期汇总控件必须显示 `区间汇总2`，底层值必须为 `tenyear`。
- 火影控制口径必须满足 `source_video_type=1`、`record_type=3`、`filter=1`、`operation_client=1..7`，并保留已加载的全部项目标签、子游戏、母渠道、负责人和产品。
- 点击查询后必须等待结果表刷新，再读取 `总计 → 花费`。
- 日期已经变化但总计仍等于上一月结果时，判定为旧结果，不得记录。

## 证据等级

- `confirmed_ui_interval`：已核验三项筛选和目标月，结果表明确显示 `总计 → 花费`。
- `confirmed_response`：同一已登录查询返回精确数值 `info.sum.cost`，且请求参数已核验。
- `inferred`：仅凭标题、截图、文件名或上下文推测；不得作为最终数字。
- `missing`：目标月没有可核验结果；数值必须为 `null`。

## 禁止混淆

- `monthly-summary`、周报归档和实时区间查询是不同数据集，不能互相替代。
- 分页素材行不是项目总消耗，不得手工求和替代总计。
- 可见选项不等于已生效筛选；必须核验控件实际值。
- `标签(category)`、`自定义标签(self_tag)`、`一类(source_type)` 和 `类型(source_video_type)` 是四个不同字段，不得混用。
- 改变筛选但未重新查询时，“导出”仍指向旧查询会话。
- 格式化金额只用于展示；最终结果保留后台精确整数。
- 素材产出数量只按自然月设置 `日期(date)`；`素材产出日期(date2)` 不按月筛选，保留本次确认的完整产出范围，用 --material-range 显式传入。
- `总数量(info.sum.count)`、查询结果行数、分页大小和 `总计→花费` 是不同指标；产出数量只读第一个。
