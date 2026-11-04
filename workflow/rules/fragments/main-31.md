## 自动化执行路径
当前执行路径：项目表读取 → PySceneDetect原片/成片拆镜 → Pillow参考图预检与总览 → faster-whisper实际语音转录 → 对照定稿核对 → WhisperX中文对齐与短句起音复核 → 原曲识别、版本核对及独立音乐文件获取 → 同一时间线输出字幕、独立音乐轨、FFmpeg审核MP4与PR工程 → PR原生打开序列、播放与保存回读 → 用户审核。
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)只生成候选镜头边界。按素材校准阈值和最短镜头时长，推拉或闪光造成的误拆先复核，不自动删片或将检测段数当作剧情分幕。
- [Pillow](https://github.com/python-pillow/Pillow)检查图片解码、尺寸、比例和重复，并输出带用途编号的参考图总览；人物身份、眼罩、瞳孔、场景与真实画布绑定仍需视觉/平台回读，不能用技术检查替代。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)记录真实声音；[WhisperX](https://github.com/m-bain/whisperX)只对核对后的文字做中文强制对齐。漏词、错词不能靠强制对齐掩盖；短句须增加可读停留，限制在下一句和成片结尾前，不能只采用逐字极短区间。
- [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html)处理恒帧副本、对白与音乐避让、字幕渲染及解码/黑帧/冻结/响度检测。审核MP4与PR共用同一组入出点、音轨文件、字幕/字卡内容和时间；不同渲染器的最终排版仍需核验。
- 本机原实施记录已实测PySceneDetect 0.7.1、Pillow 12.3.0、faster-whisper 1.2.1、WhisperX 3.8.6及py-premiere 0.1.0。视觉和语音依赖隔离，版本锁定；中文模型下载后校验SHA256并本地复用。音频由FFmpeg统一解码为数组，避免第三方音频容器接口变更。
- 本机续编入口说明：`<receiver-configured-path>`。当前工程以最新保存的PR为准，使用py-premiere最小修改并回读；`run.py all`及`build_source_music_pr.py`包含旧版固定25秒剪辑与分段配乐，已加历史重建门禁，仅显式历史复现可用独立输出目录运行，不能用于当前续编或新项目默认生成。项目表仍是素材与状态入口，timeline.json仅同步必要剪辑、字幕、音源和交付证据。
- 复用已生成素材跑后期，不自动触发付费再生成或发布。工具安装、脚本跑通、机器检查、PR原生打开、听审和用户采用分别记录；未验证项目保留待验。
