## 建项与保护性写入

建项先 list/context 定位真实项目，复用唯一 Sheet。新空表在 console.json 登记真实 project_id、工作簿、sheet_id、name、template_id="DIRECTOR-STORYBOARD-1" 和 shot_count（实际镜数，1—100）；通过 console_template.py init 初始化。禁止把旧项目配置改成新模板后直接 init；有内容时必须先做迁移映射并核对原引用。

写前加载 console-write，运行规则与模板检查。逐镜文本仍用 console_content.py check → patch；original_copy 对应 F、script 对应 G、dialogue 对应 H，景别用 shot_scale、运镜用 camera、声音用 sound、时长用 duration；都用 --index（从 0 开始）定位镜头。对照参考图片用 source_screenshots，分镜图用 storyboard_images，经 console_content.py image 按实际 SHA 挂载到目标工作簿并回读。

禁止单元格 note／评论／红角。原件与图片链接先保留，再核对本次目标与并发变化。文本写回不得改样式、标签、身份或阶段；图片上传未知先查原回执，不重传。写后回读目标内容、全部模板样式、非目标单元格与引用。读写失败停在受影响动作，不绕过版本守卫。
