---
name: paid-skit-premiere
description: 当前买量项目的可编辑Premiere续编和A段原生导出；保护手改。接B默认FFmpeg，只有明确要求时使用PR例外。
metadata:
  version: "WF20261017.2"
---

# PR续编与A段交付

A13／A14／A15按工作区workflow_node.py context返回的当前合同执行；不通读主控。需要实际PR实现时再读references/source-readme.md和当前工具帮助。
先读最新保存PR、素材、源SHA及入出点，只在候选修改目标范围；写回前复核源SHA。保留一个主序列、多轨、完整原片／备选、独立字幕／对白／连续BGM。读取成功、原生打开、编码、完整声音和用户采用分别验收。
`scripts/pr_inspect.py`只核对真实媒体路径，不代替原生打开或听审。需要脚本修改时使用已验证py-premiere；FFmpeg做技术检查与接B，不冒称A的PR导出。
B01—B05默认FFmpeg接片，用已验A和实际B入出点，不重建PR或研究嵌套透明通道。GUI连续失败按当前纠偏规则停止盲试。历史重建器不作为当前续编入口。

接口优先规范由当前节点返回：A13的premiere-automation.01及A14／A15的premiere-automation.02。默认使用工作区workflow/tools/premiere-bridge/manage.py加载已验证本机桥，以完整参数任务完成检查／原生副本／保存／PR直导A，AI读取简短回执；GUI仅补接口缺口、弹窗和必要视觉检查。A直导使用Adobe公开UXP IMMEDIATELY；本版桥0.2.1的接口回归已在维护环境验证，接收人PR版本与实际原生导出须独立验收，导出只另存新副本；unknown保留占用，序列GUID必填。其他宿主或版本变化须独立复验。未经明确授权不更新Adobe。必要实现细节见同源[接口方法](references/premiere-automation.md)，只在当前合同需要时读取。

交付前按当前合同登记包装需求来源与A／B范围；返工先封存新Vnnn和SHA回执，旧PR、媒体和QA保留。稳定业务名更新走工作区delivery_contract.promote_alias，原SHA变化停止该条，A14逐文件完整性门不替代原生导出、听审或采用。
