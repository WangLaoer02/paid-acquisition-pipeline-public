# Premiere桥接优先与原生A段交付

## PR接口执行与A段原生导出

默认本机已验证UXP桥检查、原生另存、打开候选及导A；已有脚本准备剪辑、BGM和字幕，FFmpeg接B及包装。保留唯一当前工程、主序列、多轨、原片和手改；已验A与最新工程、范围和内容一致则复用，不因换B重导A。

入口workflow/tools/premiere-bridge/manage.py：start --scope <本轮绝对目录> --original <受保护原工程>加载同版插件，bridge.py submit --request <任务JSON>提交，status --job <原ID>查简短回执。支持inspect、snapshot-copy、open-copy、export-a、restore-original。PR直导用公开UXP IMMEDIATELY；已有桥可用时不另探MCP或逐次开导出界面。已验CEP／ExtendScript仅兼容，AME队列与未记录私有接口不作默认。

先查工程路径／GUID、主序列GUID、入出点、媒体和音频／字幕轨。snapshot-copy保留未保存内存，目标已存在即拒绝；导出前须同轮snapshot-copy或open-copy建立SHA／工程GUID绑定。排队后原件、候选、预设或输出变化均停止；保存只另存本任务全新副本，不覆盖原件或候选，保存后再检查再直导。离线py-premiere仅改备份候选，写回前复核SHA，冲突重新读取；禁止旧内存覆盖磁盘。字幕沿已验SRT／工程方法，BGM用同版原曲连续区间，其他参数服从当前项目。

任务绑定唯一ID、工程路径／SHA、必填非空序列GUID、实际A入出点、画幅／帧率、显式预设路径／SHA、烧录及音视频要求、唯一输出。控制器和插件均拒绝缺失／错误GUID；写前校验许可仅一次、短期有效。检查→另存新副本→直导→核验实际输出，记录保存后SHA。EPR用当前CaptionParamContainer／Burn In格式，make_preset.py按项目画幅／帧率生成；内嵌AMEPreset和漏字幕旧Frame.io预设禁用。

受理、原生调用返回、输出技术通过、完整音画验收和采用分计。原生调用后异常记unknown，回执失败、重载／重启不释放占用；不换ID或后端重发。true后仍保留verification_required，bridge.py verify --job <原ID>核对输出后才结束；unknown须原任务终态实证，详见README。AME事件不证明PR直导完成。正常只读简短回执，有界等待；故障才读对应日志。GUI仅补接口缺口、弹窗、权限及视觉检查，两次失败纠偏。完成按需restore-original，再stop临时服务。

本机Premiere26.5.2＋桥0.2.0已在独立副本实测保存重开、直导和原件保护；异常恢复由隔离用例验证，详见维护记录。旧0.1.0证据保留；首次部署、宿主／桥变化仍须复验身份、保存重开、字幕及音频。本地开发插件重开PR后start加载；tooling、开发模式许可和账号不随源码复制。PR需运行，不承诺无头或不影响桌面；未经明确授权不更新Adobe／开发模式，安装／许可／费用分验，不恢复已停止生产／上传。细节按需读桥README。

官方依据：[工程](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/project)、[PR直导](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/src/export.ts)、[字幕边界](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/captiontrack)。

## PR导A回执与实际验收

A段回执至少包含任务ID、实际宿主／桥版本、工程路径和保存后SHA、序列GUID、实际入出点、预设SHA、输出路径和SHA、执行状态及错误码。PR原生导出来源、FFmpeg接B来源分别记录。已受理或未知结果只回查，不重复提交。

确认导出实际结束，再用ffprobe核对画幅、帧率、帧数／时长、音视频流，并完整解码。实际看首尾／切点、字幕文字及烧录位置，听完整音乐／对白并检查静音、断音、同步及音量；参数读值不能代替成片声音和字幕。将当前工程与实际导出范围／内容对应；新手改后旧A不得直接沿用。

技术检查、完整画面、完整听审和用户采用分别记录；有残留问题不得标PASS。每版接B继续独立验接点、贴片边界和片尾，并听完整成片，不能用A验收替代。默认不为B新建PR工程或导入B／贴片／水印。只回填必要路径、版本、核对结果和下一步；无异常时不让AI逐秒盯进度或反复读取全量日志。
