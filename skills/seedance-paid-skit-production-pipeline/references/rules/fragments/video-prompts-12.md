## 方法依据与适用边界
- [Seedance 2.0 官方说明](https://seed.bytedance.com/en/blog/official-launch-of-seedance-2-0/)展示多模态、故事板参考与多镜头输出，也指出多主体一致性仍有改进空间；不将示例视作成功保证。
- [Runway 图生视频指南](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide)建议图像确定视觉、文字聚焦运动，并先清理输入瑕疵。此处仅借鉴制作方法，不将 Runway 参数套用到 Seedance。
- [Adobe 剪辑基础](https://www.adobe.com/in/creativecloud/video/discover/edit-a-video.html)将情绪、叙事、节奏和空间连续性作为剪辑判断依据；[StudioBinder 运镜](https://www.studiobinder.com/blog/different-types-of-camera-movements-in-film/)与[反应镜头](https://www.studiobinder.com/blog/what-is-a-reaction-shot-definition/)用于设计推拉的情绪目的与对白间的反应节拍。
- [Google 六秒叙事案例](https://business.google.com/uk/think/marketing-strategies/youtube-bumper-ads-six-second-storytelling/)用于借鉴短时长内聚焦关键转折的方法，不将 YouTube 案例直接当成抖音投放效果证明。
- [THE LINE《Take Over》制作解析](https://thelinestudio.com/work/league-of-legends-worlds-2020)以人物动画、三维空间运镜及动作节点特效形成节奏；[《Season Start》导演复盘](https://www.kolyukh.com/projects/ss18)先确定主题与递进，再用动态预演校准镜头和表演。借鉴空间调度与强弱变化，不将战斗速度线、闪帧强套到家庭对白戏。
- 会话“火影类视频生成”的测试证据：明确参考职责、真实引用和人物位移曾改善结果；近景开场和侧向跟随改善空间，但未解决碰撞拖慢；粗绘板曾污染画风，特效增强曾产生气泡状水滴。仅复用已观察到的改善，不将整套实验标为已验证，不套用该会话的 Seedance 2.5 参数。
- 首尾帧槽位、数量、时长与参考模式以当前即梦 CLI 的 schema 和模型查询为执行依据；单个项目的具体镜头、台词及14秒安排不是强制模板。
