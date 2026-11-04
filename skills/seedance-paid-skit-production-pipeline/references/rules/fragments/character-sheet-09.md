## 7. FAIL / Repair
- `FAIL_IDENTITY / FAIL_OUTFIT` → 回 Master，重做当前项。
- `FAIL_VIEW / FAIL_GEOMETRY` → 锁定关键线与比例，只重做当前视图。
- `FAIL_NOISE / FAIL_FAKE_TEXTURE` → 只清理高频伪细节，保留身份、构图、几何、颜色、光影与真实材质；禁止以“清晰化”为名整张重构。
- `FAIL_TRANSPARENCY / FAIL_BACKGROUND` → 人物合格时优先非生成式 Alpha/抠图修复，否则重做当前项。
失败只阻塞受影响项；优先复用合格原件或非生成修复，确需重生仍须有真实缺口与费用授权。修复后重新File QA + Turnaround QC，不覆盖已采用原件。
