## 0. 状态机
仅加载当前阶段：`Reference Gate → 已有素材与目标输入核对 → 复用或必要补图 → File QA → Turnaround QC → Repair/Advance → 入库`。
- `PASS → AUTO_CONTINUE → next_item`
- `FAIL → FIX_CURRENT → QA`
- `QUEUE_EMPTY → COMPLETE`
已采用合板满足当前任务和目标模型实际输入时直接复用，不因通用独立视图要求新增生成。确有补图任务时，除真实歧义、权限或工具阻塞外，不因单张完成而暂停；生成一张成功图片不是多图任务的结束条件。
