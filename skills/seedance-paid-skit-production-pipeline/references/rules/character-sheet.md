**character-turnaround-generator · v1.4.0**
## 0. 状态机
仅加载当前阶段：`Reference Gate → 已有素材与目标输入核对 → 复用或必要补图 → File QA → Turnaround QC → Repair/Advance → 入库`。
- `PASS → AUTO_CONTINUE → next_item`
- `FAIL → FIX_CURRENT → QA`
- `QUEUE_EMPTY → COMPLETE`
已采用合板满足当前任务和目标模型实际输入时直接复用，不因通用独立视图要求新增生成。确有补图任务时，除真实歧义、权限或工具阻塞外，不因单张完成而暂停；生成一张成功图片不是多图任务的结束条件。
## 1. Reference Gate
命名 IP 无 Approved Master、用户反馈“不像/服装不对”、版本有歧义时，先联网实际查看官方角色页、官方设定或原作画面；搜索摘要不能代替看图。
锁定唯一 Master：`face / hair / eye / body / outfit / asymmetry`；可用已采用原图或合板，保留原件、来源、SHA与用户采用范围，不将技术QA当用户采用。
参考不足不编造；不可见背部只做最小一致补全，并标记 Review。Gate 未通过不生图。
## 2. Turnaround Locks
三视图共享同一 Master，强制保持：
- **Identity**：脸型、五官、发型、年龄感、体型。
- **Geometry**：总身高、头身比、肩宽、腰线、胯线、膝位、腿长、脚底高度。
- **Outfit**：服装结构、分层、配件、鞋、左右不对称关系，不凭空增减。
- **View**：F=纯正面；L/R=严格 90°；B=纯背面。禁止 3/4、转头、扭胯、透视夸张。
- **Surface**：只保留参考中真实存在的材质；表面连续、色块干净、阴影平滑，限制随机高频微细节。
## 3. Queue 与实际交付合同
先核对已采用原件、当前任务用途与目标模型实际输入规格/绑定；已采用合板满足输入且跨视图QC通过时直接复用，交付实际原件，不强制独立图或新生成。
只有当前任务或目标模型确需独立视图时，才记录具体缺口及依据，按`look/F → look/L → look/B`补缺；已有合格独立原件优先复用，不能为凑齐通用队列重做。
仅新生成独立视图时：**1 generation call = 1 character × 1 look × 1 view × 1 standalone PNG。**默认单人全身、自然站立、中性表情、正交式构图；背景按项目要求。
独立生成分支禁止拼板、一图多视角/多服装、无关文字、色卡、边框和场景；这项限制不排除已采用合板的复用。
实际接口若需从合板裁切输入副本，须保留原件和派生关系；禁止裁切冒充原始独立生成，不新增未经授权的图像任务。
## 4. Prompt 最小化
仅在确有已授权补图缺口时编写Prompt：身份锁 + 唯一look + 唯一view + 全身 + 正交构图；透明或底色按项目要求，不为复用原件另写生成任务。
编辑/补视图时明确：`change only current view; preserve identity, geometry, outfit and proportions`。
优先正向描述目标材质：`clean continuous surfaces, coherent material regions, smooth tonal transitions, restrained micro-detail`。
不要为了“高清”自动加入 `8K / extreme detail / rich texture / hyper sharp / film grain`。
不要堆砌 negative prompt；只写与当前失败直接相关的必要禁止项。
## 5. File QA Gate
对复用和补图均读取实际采用原文件，保留来源、SHA与真实文件形式：
- 文件可解码；同一角色、同一造型，视图与本次用途对应；独立图分支才要求单文件单视角，合板逐面核对；
- 项目要求透明时检查Alpha、实质`alpha=0`区域、安全边距及黑白底可见边缘；RGBA或全透明像素RGB不能单独证明通过/失败；
- 无影响当前用途的无关文字、背景物、伪棋盘格和光晕；已采用合板的分面形式不单独构成失败；
- 视角正确；身份、比例、发型、服装未漂移；
- 无明显随机颗粒、假毛孔、假布纹、假划痕、锐化噪声。
记录可得的 `mode,width,height,alpha_min,alpha_max,transparent_ratio`。RGBA 本身不等于透明。
## 6. Turnaround QC
同一look已有≥2个视图时执行跨视图检查，包含同一合板内各面；复用不能跳过QC：
1. **结构优先于表面质量。**
2. 对齐头顶、下巴、肩线、腰线、胯线、膝线、脚底；关键高度应基本一致。
3. 检查发型轮廓、服装分层、配件位置、色彩关系能否从一个视角连续解释到另一个视角。
4. 单张漂亮但跨视图不一致 = FAIL。
5. QA 不通过的图不得作为下一视图 Master。
## 7. FAIL / Repair
- `FAIL_IDENTITY / FAIL_OUTFIT` → 回 Master，重做当前项。
- `FAIL_VIEW / FAIL_GEOMETRY` → 锁定关键线与比例，只重做当前视图。
- `FAIL_NOISE / FAIL_FAKE_TEXTURE` → 只清理高频伪细节，保留身份、构图、几何、颜色、光影与真实材质；禁止以“清晰化”为名整张重构。
- `FAIL_TRANSPARENCY / FAIL_BACKGROUND` → 人物合格时优先非生成式 Alpha/抠图修复，否则重做当前项。
失败只阻塞受影响项；优先复用合格原件或非生成修复，确需重生仍须有真实缺口与费用授权。修复后重新File QA + Turnaround QC，不覆盖已采用原件。
## 8. 输出与入库
复用沿原名和SHA登记实际合板/独立图形式及采用范围，不为命名重生成或覆盖原件；仅新独立图命名：`{character_id}_{look_id}_{F|L|R|B}_v001.png`。
失败资产不入库；未人工批准保持 Review。
用户要求入库时，**每张资产在 File QA + Turnaround QC 通过后立即调用 ****`paid-skit-asset-bridge`**** 入库**，不等待整组队列完成。只有 Canonical 正文 + Files 预览 + Final Fetch 全通过后，该张才算 DONE 并允许进入下一项。入库失败保留同一原件并恢复入库，禁止重生图。
