---
name: paid-skit-character-format
description: 仅在获准修改角色目录、页面或版本索引时读取对应规则；普通物料查找和生成不以目录整理为前置。
metadata:
  version: "1.1-local-asset"
---

# 按需角色目录维护

A05／A06确实需要且已获准修改角色库字段、页面或版本索引时，读取工作区 `python3 scripts/workflow_node.py context --item <真实item_id> --condition character-catalog` 的适用片段。A04只确定物料需求，不在此入口提前锁原件或改目录；普通查找沿原物料记录，不要求另造清单或整理图库。

库结构按项目实际入口；历史案例和专属造型约束不跨项目套用。实际归档、外部写入、生成、费用与采用分别沿原授权核验，安装不授予权限。
