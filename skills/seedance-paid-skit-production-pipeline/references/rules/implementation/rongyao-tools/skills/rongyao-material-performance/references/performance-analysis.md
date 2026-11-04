# 素材表现分析模式

先按统一主Skill的查询契约选择 `run` 或 `analyze`；本文件只定义拿到数据后的分析和复用方式。导出和分析共用原 material_performance.py 脚本，不额外建立抓取链。

## 分析与输出

- 新产素材默认在同份投放CSV内按目标周期的产出日期拆分，不为拆分重新抓取；该样本不代表完整生产台账。
- 观察消耗500元、ROI1 9%、2日倍率1.9是Skill分析参数，不冒称用户确认的业务标准；用户明确阈值优先。
- 缺失值为null，真实0保留0。后台总计与明细汇总及差额分开；角色和方向可重叠，不能相加充当总体。原始素材链接不改写，链接存在不代表已观看视频。
- 成功后优先读取命令末尾JSON摘要、summary.json或focus-summary.json。方向摘要保留全部已识别方向，角色摘要保留头部12组并报告总组数；已识别方向不等于完整后台分类。
- 用户只要数据结论时直接回答，不额外构建报告、图表、Notebook或发布。代表素材等摘要外证据从本次CSV定向读取，不重抓数据。
- 未查询对比期不写“提升/下滑”；未核验视频只作指标和标签判断，不编造内容因果。无真实数据不判断真实优质方向。

## 复用和单角色对比

已有CSV先核验项目、双日期范围、来源时间、必要字段；当前口径变化或来源过旧不能静默复用。一次导出后继续分析同一数据，直接用 `analyze`，不再运行 `run`。

以下命令在 rongyao-material-performance 目录执行。新产日期按本次请求解析，不套历史示例。

```sh
python3 scripts/material_performance.py analyze --current <已核验CSV路径> --new-start <产出开始日> --new-end <产出结束日>
python3 scripts/material_performance.py compare-role --role 凯 \
  --current <已核验当前期CSV> --current-summary <当前期摘要> \
  --current-range <当前期范围> --compare-range <紧邻等长上一期> \
  --material-range <已确认素材范围> --gid 193 --output-dir <新的空目录>
```

单角色对比只补查缺少的对比期；所有查询保护继续沿统一主Skill。分析判断另读本目录 judgment-contract.md，需要内容结论时再按证据规则核验视频。
