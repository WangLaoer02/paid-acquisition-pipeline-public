# 高成本素材编号与原创素材查询

日期示例仅说明格式；实时操作必须传 --material-range 指定当前已确认的完整产出范围。历史控制值不随包迁移，没有本次校准输入时 calibration.passed=null。

## 为什么需要专用路径

`group=material_serial_number` 的每个编号行都会内嵌该组全部素材名称和明细。`info.count` 只是编号组数，响应体却可能覆盖数千至上万条素材。它不能使用普通汇总指标的并发抓取方式。

## 强制执行顺序

1. 使用单实例锁；发现已有实例时立即停止，不叠加请求。
2. 先用 15 秒上限读取后台页面配置。超时、504 或登录失效时写 `backend_unhealthy` 并停止。
3. 动态获取一次 `category`、`pkid` 和 `pcid`，整个日期区间复用。
4. 首次查询固定 `group=material_serial_number`、`page=1`、`search[submit]=1`。
5. 记录 `info.rand`、`info.totalpage`、`info.count` 和 `info.sum.count`。
6. 第 2 页起只发送翻页请求：复用原筛选和 `rand_num=info.rand`，不再发送 `search[submit]=1`。
7. 串行读取页面；每页完成后立即汇总指定编号，不保留无关素材详情。
8. 任一页失败即停止，保留已确认页并把整批状态写为 `missing`；不得把部分和当最终值。

## 负载与熔断

- 并发数固定为 1，不提供 workers 参数。
- 默认不自动重试重查询。504 后立即结束，避免重试风暴。
- 不对每个编号分别发查询；一次编号汇总覆盖目标区间，再从返回页筛选用户给定编号。
- 不在后台不健康时循环探测；一次预检失败后把恢复决定交给下一次明确运行。
- 运行结束或中断后不得留下后台进程。

## 原创判定

对用户指定的素材编号，只统计素材名称满足以下任一条件的唯一素材：

1. 名称包含 `原创`；
2. 名称以 `YYMMDD + 编号 + 序号` 开头，并在后半段再次出现相同的独立编号。

两条同时命中只计一次。独立编号使用字母边界判断，例如开头为 `ZX` 时，后缀 `-ZX` 命中，`-XGA` 不命中。保留用户给出的编号清单，不自动加入或排除 XG。

## 专用脚本

```bash
python3 scripts/capture_original_materials.py \
  --start-date 2025-01-01 --end-date 2025-06-30 \
  --project 火影 --project 咒术 --project 烈焰 \
  --code ZX --code WY --code HR
```

机器输出必须包含：`distinct_code_count`、`candidate_material_count`、`original_marker_count`、`repeated_code_count`、`overlap_count`、`matched_unique_count`、`pages_expected`、`pages_completed`、`status` 和 `blocker`。
