# GitHub一手来源与取舍

核验日期：2026-10-25。用于查证本Skill的方法或评估新增工具，不在每次创作时全量读取。下表的工作流程为结合本项目的设计取舍，属于历史方法研究，不是当前Seedance运行依赖，也不保证本用户角色或Seedance能达到某种效果。

| 一手来源 | 已核对内容 | 本Skill采用的方法与边界 |
|---|---|---|
| [MiniMax H3官方提示词Skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md)、[首尾帧指南](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt)、[全参考指南](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt) | 首尾帧描述连续路径；全参考将可复用的主体内容与具体帧/分镜锚点分开 | 按职责映射三视图、服装、场景、动作与关键帧；模式以当前工具实测为准，参考标签不是硬控制槽；官方重写协议不覆盖用户的中文精简交付要求 |
| [Diffusers IP-Adapter](https://github.com/huggingface/diffusers/blob/main/docs/source/en/using-diffusers/ip_adapter.md)、[ControlNet](https://github.com/huggingface/diffusers/blob/main/docs/source/en/using-diffusers/controlnet.md) | 外观参考与姿态/深度/边缘等结构控制可以分工，支持相应管线的编辑与局部重绘 | 优先用现有图像工具实现形象与布局分工、同基准编辑；这些不是Seedance参数，也不是当前图片工具已实现的功能；FaceID未经验证不用于固定面具或动漫脸身份判断 |
| [StoryDiffusion](https://github.com/HVision-NKU/StoryDiffusion/blob/main/README.md) | 为跨图一致性提供专门实现；README中的提示词数量条件针对该实现，视频代码/权重仍有未完成项 | 借用成组设计与共享角色/场景基准的思路，不把其最少提示词数变成通用关键帧数，不将展示视频视为当前工具已可复现 |
| [Storyboarder](https://github.com/wonderunit/storyboarder/blob/master/README.md) | 以快速草图与animatic测试故事表达，可连接图像编辑与导出 | 先用已有图/低细节布局判断构图和节奏，再精修；静帧预演不证明真实动态成立，不要求安装该应用 |
| [VBench](https://github.com/Vchitect/VBench/blob/master/README.md)、[I2V分支](https://github.com/Vchitect/VBench/blob/master/vbench2_beta_i2v/README.md) | 分别评估主体、背景、运动、动态程度和画面质量等维度 | 组织人工全片/连续帧检查，另查切点、接触和声音；不以自动总分替代物理、审美或用户采用，不默认部署评测模型 |

本次仅引用与提炼方法，未安装仓库、复制实现、下载模型权重或执行外部Skill。未来确需部署时另核对当前版本、许可、硬件和实际输入能力，沿现有任务范围执行。
