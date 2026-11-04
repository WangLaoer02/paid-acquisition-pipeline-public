# 音画核验与依赖诊断

仅在需要ASR、听审/连续观看受阻或明确维护依赖时读取；普通下载、已有充分观察不额外调用。

## 先区分真实能力

| 方式 | 可证实 | 不可代替 |
|---|---|---|
| 机器ASR | 后端从实际音轨输出的候选文字和估计时间 | 原声逐字正确、说话人身份、非语音声音、主观听审 |
| 实际听审 | 有受支持音频输入能力的模型或人工真实听到并记录的内容 | 未听范围、静态字幕；模型必须有工具实际返回音频感知输入 |
| 连续观看 | 有受支持视频输入能力或人工实际连续观察的时间范围 | ffmpeg解码、播放器启动/播放、截图轮询 |
| 抽帧观察 | 已实际查看的帧及其时间、可见动作阶段、画面文字 | 采样间动作、音频、整片连续观看 |

工具只返回JPEG时保留抽帧范围。字幕属于画面文字，ASR属于机器候选；两者一致可交叉参考，不自动标“已核听”。ASR/OCR统计值不换算为内容正确率。音乐/音效不得由画面或能量峰推定。

A01沿当前目标选范围，保留上一版分类与两层交付：短事实表加三条简短判断。只有影响所选内容判断的缺口阻塞对应结论；不为无关BGM名称或微动作加门槛。用户明确要求完整音画验收时，未完成听审/连续观察应明确不通过该范围，不能降级后沿用“完整通过”。不增加确认点或自动进入A02。

## 当前入口

```bash
python3 /实际Skill目录/scripts/fast_transcribe.py --diagnose --probe-workers
python3 /实际Skill目录/scripts/fast_transcribe.py /原片.mp4 --out /任务目录/asr.txt --evidence /任务目录/asr.json --json
```

保留旧input/--out/--output-dir/--json接口和下载器的`transcribe_audio(audio_path, language, model, work_dir)`调用。脚本不新建服务、不安装依赖、不改变登录。失败返回安全错误码与各后端attempts；不保存/回显URL、原始服务响应或含凭据stderr。worker默认每项15秒，可由`TRANSCRIBE_WORKER_TIMEOUT_SECONDS`明确调整；本地后端默认600秒。

- `not_configured`：没有worker配置；与服务离线不同。
- `service_offline`：当前连接拒绝；`timeout`/`network_error`分别保留；不是缺凭据。
- `permission_denied`：401/403；不自动改凭据或绕过权限。
- `dependency_missing`：分别查看可执行文件/环境与模型是否存在。
- `FASTER_WHISPER_IMPORT_FAILED`：配置的解释器不能导入包。
- `execution_failed`/`FASTER_WHISPER_EXECUTION_FAILED`：已有环境实际执行失败；faster-whisper另保留model_load/pcm_decode/inference等阶段及安全异常类型，先核版本和输入，不当作“没有安装”。
- `AUDIO_STREAM_MISSING`/`AUDIO_DECODE_FAILED`：输入没有音轨或解码失败，不判为ASR后端缺失。
- `ASR_UNAVAILABLE`：各尝试均未取得非空转写，具体根因在attempts。旧输出文件可能仍在，失败时不可复用为本次成功。

`--diagnose`只做依赖检查；可选`--probe-workers`仅探测配置的loopback TCP端口，不上传媒体、不假设任意端口存在服务。远程服务按已有入口与授权核验，配置发现不等于新上传许可。

## 主机配置（不随Skill包复制）

`DOUYIN_TOOLS_CONFIG`或`~/.config/seedance-douyin-video/config.json`保留原字段；只增加所需路径，避免覆盖原URL/手改。faster-whisper按模型名映射本地目录：

```json
{
  "faster_whisper_python": "/已核环境/bin/python",
  "faster_whisper_models": {"tiny": "/本机模型快照目录"}
}
```

可用环境变量覆盖：`FASTER_WHISPER_PYTHON`、`FASTER_WHISPER_MODEL_DIR`。显式模型目录须与请求模型对应，维护者核对目录内config与来源，不按资产文件名猜模型。已有`WHISPER_CPP_BIN`/`WHISPER_CPP_MODEL`、`WHISPER_BIN`和worker配置仍支持。Python Whisper使用`WHISPER_MODEL_DIR`下已存在的`<model>.pt`，默认缓存`~/.cache/whisper`；不触发自动下载。

faster-whisper通过独立解释器调用包内helper，以CPU/int8运行；模型目录用`local_files_only=True`。FFmpeg把音轨规范为单声道16 kHz PCM WAV，helper经stdlib wave转成数组，避免共享环境PyAV解码接口漂移。包/模型准备仅在明确依赖修复授权内进行；先找已有受支持环境与模型，不全局升级。日常默认tiny，其他模型沿既有明确精度要求与`ALLOW_SLOW_WHISPER`边界。

## 真实样本验收与恢复

记录原片SHA、总时长和音轨、实际后端/版本/模型SHA、ASR源时间及正文。`--evidence`时间相对输入文件起点，若输入切片，另记录切片对应原片起止；ASR时间不是核听过的剪辑点。抽帧证据记录实际查看范围，机器解码记录独立保存。

无可用听审/连续视频输入工具时，提供本地原片或必要的带上下文切片、精确复核问题，交具备感知能力的下一执行者或人工；不要通过播放假装已感知。可先交“转写恢复/抽帧完成，完整音画仍未验收”，不把未知字段改为通过。不自动上传原片到云服务以补能力。
