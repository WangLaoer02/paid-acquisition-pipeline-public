# 抓取输出契约

日期示例仅说明格式；实时操作必须传 --material-range 指定当前已确认的完整产出范围。历史控制值不随包迁移，没有本次校准输入时 calibration.passed=null。

## 人工输出

先写口径，再只列用户要求的结果：

```markdown
抓取口径：火影＝母游戏“忍界大战(193)”｜自然月｜区间汇总｜总计→花费｜元

| 月份 | 日期范围 | 消耗（元） | 状态 |
|---|---|---:|---|
| YYYY-MM | YYYY/MM/01-YYYY/MM/DD | 123456 | 已确认 |
| YYYY-MM | YYYY/MM/01-YYYY/MM/DD | — | 缺失 |
```

结尾只写已确认数、缺失数和捕获方式。不要附加趋势、同比环比或素材分析，除非用户要求。

## 机器输出

```json
{
  "request": {
    "project_alias": "火影",
    "project_field": "母游戏",
    "project_label": "忍界大战",
    "project_id": 193,
    "grain": "calendar_month",
    "aggregation_method": "interval_total",
    "date_group": "tenyear",
    "metric": "spend",
    "metric_location": "总计.花费",
    "unit": "CNY",
    "timezone": "Asia/Shanghai"
  },
  "rows": [
    {
      "month": "YYYY-MM",
      "date_start": "YYYY-MM-01",
      "date_end": "YYYY-MM-DD",
      "spend": 123456,
      "status": "confirmed_ui_interval",
      "source_type": "authenticated_dashboard_interval_query"
    }
  ],
  "observed_at": "RFC3339"
}
```

## 状态规则

- 成功读取：`confirmed_ui_interval` 或 `confirmed_response`。
- 无精确结果：`missing`，`spend` 必须为 `null`。
- 筛选正确但结果尚未刷新：`pending_refresh`，不得沿用旧数值。
- 多个同口径来源冲突：`conflict`，保留各值，不静默选择。

## 素材产出数量输出

```markdown
抓取口径：日期=自然月｜素材产出日期=后台默认全范围（不按月筛选）｜否定词留空｜视频｜区间汇总｜总数量｜条

| 月份 | 项目 | 素材产出日期 | 日期观察窗口 | 产出数量（条） | 状态 |
|---|---|---|---|---:|---|
```


## 原创素材计数输出

```markdown
抓取口径：指定素材编号｜名称含“原创”或后缀重复开头编号｜唯一素材｜素材产出日期保持后台默认

| 日期范围 | 指定编号数 | 候选素材数 | 原创素材数 | 状态 |
|---|---:|---:|---:|---|
| YYYY/MM/DD-YYYY/MM/DD | 13 | 1234 | 456 | 已确认 |
```

只有 `pages_completed == pages_expected` 且所有指定编号均完成检查时才能输出 `confirmed_response`。超时、504、会话变化或分页不全时，`matched_unique_count` 不得作为最终数，状态写 `missing` 或 `backend_unhealthy`。
