---
name: paid-skit-asset-bridge
description: 原件、预览和唯一资产入口的归档／恢复；不承担无关阶段。
metadata:
  version: "WF20261010.6"
---

# 原件、预览和唯一资产入口的归档／恢复

适用节点：实际归档节点。先由工作区`python3 scripts/workflow_node.py context --item <真实item_id> --condition asset-archive`取得当前合同，只读本节点要求的对应片段。条件分支仅实际匹配时启用；普通任务不预读完整主控或全部角色格式。

执行按当前真实输入、工具权限及Gate；未知／失败不伪造采用，费用和写回分别核对。原完整方法保留在同版policy-index及archive，缺少现有方法时按主题定位，不从旧版本整页续接。
