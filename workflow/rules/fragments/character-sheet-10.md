## 8. 输出与入库
复用沿原名和SHA登记实际合板/独立图形式及采用范围，不为命名重生成或覆盖原件；仅新独立图命名：`{character_id}_{look_id}_{F|L|R|B}_v001.png`。
失败资产不入库；未人工批准保持 Review。
用户要求入库时，**每张资产在 File QA + Turnaround QC 通过后立即调用 ****`paid-skit-asset-bridge`**** 入库**，不等待整组队列完成。只有 Canonical 正文 + Files 预览 + Final Fetch 全通过后，该张才算 DONE 并允许进入下一项。入库失败保留同一原件并恢复入库，禁止重生图。
