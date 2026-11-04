---
name: paid-skit-character-sheet
description: 核验或补充当前实际需要的角色三视图；已有合格原件直接复用，不要求齐套。
metadata:
  version: "1.1-local-asset"
---

# 按需三视图

A05实际需要跨视图核验、或A06确有三视图补充缺口时，读取当前工作区 `python3 scripts/workflow_node.py context --item <真实item_id> --condition character-turnaround` 返回的方法。工作流决定当前产物与采用范围，既有同文件同用途有效检查直接复用，变化才重核；A05不制作新资产，A06只补真实必要缺口。

三视图及必要母版默认原生动画风2.0；明确指定或已采用母版风格优先。此默认与安装／读取均不授权生成、费用或采用。实际图像工具只在确需且已授权时读取并使用，不从旧A05名称推定必须生成或凑齐独立图。
