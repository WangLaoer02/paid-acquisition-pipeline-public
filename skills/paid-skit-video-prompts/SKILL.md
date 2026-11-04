---
name: paid-skit-video-prompts
description: 真实图像绑定与视频执行提示词；不承担无关阶段。
metadata:
  version: "WF20261012.11"
---

# 真实图像绑定与视频执行提示词

适用节点：A07成稿、A08局部同步、A09真实绑定与提交准备。先由工作区`python3 scripts/workflow_node.py context --item <真实item_id>`取得当前合同，只读本节点对应片段；A07沿seedance-prompts写作，A08／A09确需扩展提示词核对时才追加prompt-authoring，不为已完成同版正文重复加载。用户要求固定原视频动态结构或从用户成品反推时，追加`--condition video-reference-transfer`读取对应方法。条件分支仅实际匹配时启用；普通任务不预读完整主控或全部角色格式。

执行按当前真实输入、工具权限及Gate；未知／失败不伪造采用，费用和写回分别核对。原完整方法保留在同版policy-index及archive，缺少现有方法时按主题定位，不从旧版本整页续接。
