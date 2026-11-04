## 1. 读取当前节点

有真实管线item才在工作区运行 `python3 scripts/workflow_node.py context --item <真实item_id> --condition backend-upload --format json`，读取当前节点与必要规则；独立文件委托仍分别核验本文件授权。已读取且同版的context直接复用；独立本地文件不虚构item或要求通过项目节点。逐节点路由见 `workflow/node_skills.json`；用本 Skill 的 `scripts/entry.py route --workspace <工作区> --node <实际节点ID>` 查询关联 Skill、规则和产出要求。

A01—A14继续来源、创作、生成、后期及验收；B01—B04继续匹配、剪辑、导出及验收。A15或B05归档后，有实际验收文件及单独上传授权才进入本专项。LIBRARY04只是可接素材，不能自动视为广告成片。用户直接提供视频可以独立委托上传，但须核对该文件、用途和明确上传授权，不能替项目通过前置节点。本专项是“非原单选节点”，不新增、替换或推进原15／5／4节点；上传成功不表示内容采用或广告发布。

