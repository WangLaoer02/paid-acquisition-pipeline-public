---
name: rongyao-material-performance
description: "荣耀新素材2.0统一工作流的兼容入口，用于火影/忍界大战素材查询、CSV导出与消耗、ROI、角色方向分析。沿用rongyao-dashboard-filter-finder的同一查询和导出契约。"
---

# 荣耀新素材2.0（兼容入口）

执行前读取[统一主Skill](../rongyao-dashboard-filter-finder/SKILL.md)，根据用户目的选查询、导出或分析模式。本入口不维护第二套认证、日期或导出规则，不先查询再转交主Skill重复查询。

原 `scripts/material_performance.py` 路径继续兼容：`export`只交付CSV，`run`共用同一抓取流程并分析，`analyze`分析已有CSV，`compare-role`复用当前期并补查对比期。旧 `run` 调用无需修改。

分析细节见[分析模式](references/performance-analysis.md)与[判断契约](references/judgment-contract.md)；共用字段、日期、缓存和完整性要求见[查询契约](references/query-contract.md)。
