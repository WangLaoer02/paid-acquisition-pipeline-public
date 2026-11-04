## Workflow
1. 确定 scope，Fetch 目标页面/数据库 schema。
2. 涉及数据库或 Skill Library 时，先结构化查询当前/历史/重复记录。
3. 用多组高置信模式 Search 建立候选；不根据 Search snippet 直接删除。
4. 每个候选必须 Fetch。
5. 按 REMOVE / PRESERVE / REVIEW 分类。
6. 正文优先最小 `docs +update` 的精确 block 更新或 `sheets +cells-set` 的最小字段更新；纯脏副本优先移到指定归档区，不让它继续占活动库。只有工具支持且删除范围明确时才真正删除。
7. Skill Library 强制检查同一 Skill ID 的 Canonical：默认只能有一个 Active + 当前记录；历史版本不得继续占活动执行面。
8. 修改后逐页 Final Fetch；按修改前语义清单逐项核对保留项、依赖、附件和授权边界，执行适用的回归检查；数据库重新 query。写入成功或关键词消失不能单独判定无损。
9. 再做关键词扫描兜底。Search 索引若滞后，以当前 Fetch 为准。
10. 最终报告实际检查范围、已修复项、保留能力、回归结果、review、错误及未同步位置；详细原文与差异留在独立审计记录。没有完整基线时不宣称全量无损。
