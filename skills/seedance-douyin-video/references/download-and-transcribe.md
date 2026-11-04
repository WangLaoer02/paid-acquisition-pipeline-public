# 抖音来源采集与音频工具

仅下载、转写、SRT、BGM或音效定位时读取本文件对应部分；分析Seedance提示词不需要全量加载。下面脚本入口和既有来源恢复规则保留。

## 功能一/二：无水印下载 + 文案提取

从抖音分享链接获取无水印视频下载链接, 下载视频, 并使用语音识别提取视频中的文案, 自动保存到文件.

### 快速转写入口

所有“视频下载 + 语音识别 + 文案改写/提取”场景，优先使用本 Skill 的快速转写脚本，不要手写 `whisper --model large/medium/turbo`：

```bash
python3 ~/.agents/skills/seedance-douyin-video/scripts/fast_transcribe.py "/path/to/video-or-audio.mp4" --out "/path/to/transcript.txt"
```

规则：
- 只有主机已配置 `LOCAL_TRANSCRIBE_URL` 或 `~/.config/seedance-douyin-video/config.json` 的 `transcribe_urls` 时才调用worker；新机器不假设存在4175/4174服务。`DOUYIN_TOOLS_CONFIG`可指定配置文件，`LOCAL_TRANSCRIBE_URL=""`显式停用worker。
- worker 不可用时尝试 `whisper.cpp`。
- 随后尝试显式配置的 faster-whisper 独立Python环境与本地模型；最后兜底已安装 Python Whisper `tiny`。各后端仅使用已准备的模型，不运行时下载。
- 只有用户明确要求高精度逐字稿/字幕归档时，才允许 `ALLOW_SLOW_WHISPER=1 whisper ... --model medium/large`。

### SRT 字幕（仅明确要求时）

原片拆解默认只记录影响故事理解的关键字幕。用户明确要求SRT文件时，才按实际音轨与当前稿对齐时间码，输出到当前任务目录；采样时间或均分时长只能作为待校草稿。

`scripts/srt_workflow.py` 是可选的字幕格式工具。它的状态保存在运行目录的 `.srt-workflow/latest.json`，默认输出在运行目录的 `outputs/subtitles/日期/`；先进入当前任务目录，或显式指定 `--out-dir`。默认不复用上一次时间码；只有用户明确要求沿用同一任务时间码且核对相符后，才使用 `make --use-state`。

交付使用当前会话支持的文件链接或附件。字幕请求不代表授权向其他聊天、飞书或其他渠道发送消息。

### 本地视频 BGM / 音效定位入口

当用户上传本地 MP4/音频并要求“找 BGM / 找中间某个音效 / 把音效切出来”时，先走确定性本地探针，不要在 live 任务里安装或试探 `shazamio`、`chromaprint/fpcalc`、`demucs`、Python Whisper 大模型：

```bash
python3 ~/.agents/skills/seedance-douyin-video/scripts/local_audio_probe.py "/path/to/video.mp4" --json
```

规则：
- 该脚本只依赖 `ffmpeg/ffprobe`，会输出 `summary.json`、波形图、频谱图、能量窗口 CSV、候选音效切片。
- 它用于快速定位和切片，不承诺识别精确歌曲名。
- 如果输入是抖音链接，要优先用 `scripts/extract_bgm.py` 读抖音元数据里的 `music.title/author/mid`，不要转去页面 Playwright 抓取，除非元数据脚本明确失败。
- 如果必须做外部识曲，只能在主任务回复/切片完成后另起短超时实验；不能阻塞当前任务。
- Python 3.14 下 `shazamio` 依赖的 `audioop/pyaudioop` 路径不稳定，禁止作为默认 live 路线。

## 功能概述

- **获取下载链接**: 从抖音分享链接解析出无水印视频的直接下载地址 (无需 API 密钥)
- **下载视频**: 将无水印视频下载到本地指定目录
- **提取文案**: 通过快速本地转写脚本/语音识别从视频中提取文字内容
- **自动保存**: 每个视频的文案自动保存到独立文件夹 (视频ID为文件夹名)

## 状态检查

本 Skill 的状态面用于确认快速转写链路是否在线：

```bash
# 如已配置worker，用其实际健康检查入口核验；未配置直接用本地后端。
python3 ~/.agents/skills/seedance-douyin-video/scripts/fast_transcribe.py --diagnose --probe-workers
```

诊断只检查依赖和已配置本机端口，不提交媒体；`tcp_reachable`、包可导入和模型文件存在都不等于转写成功。最终以真实文件运行结果为准，`--evidence /任务目录/asr.json`可保存原片SHA、后端/模型、ASR时间与正文、尝试记录。错误、配置与服务信息不输出URL或凭据；故障分类、可迁移主机配置和音画证据边界见[音画核验与依赖诊断](asr-verification.md)。日常仍默认tiny，不因缺后端静默升级模型。

## 环境要求

### 依赖安装

```bash
pip install requests ffmpeg-python
```

### 系统要求

- FFmpeg 必须安装在系统中 (用于音视频处理)
- macOS: `brew install ffmpeg`
- Ubuntu: `apt install ffmpeg`

### 文案提取配置

文案提取功能可使用本机已经配置的硅基流动凭据。支持的变量名为
`API_KEY`、`DOUYIN_API_KEY` 或 `SILICONFLOW_API_KEY`；请仅通过本机密钥管理
或当前任务已授权的执行环境注入值，绝不把赋值示例、实际值或密钥文件同步到 Skill
目录或 GitHub。

凭据获取入口：<https://cloud.siliconflow.cn/>。

如果没有 API 密钥，脚本会优先尝试本地 worker / `whisper.cpp`，再兜底到 Python 版 `whisper tiny`：

```bash
# 推荐：whisper.cpp 小模型适合“提取文案/改写”链路，速度明显快于 Python whisper large/turbo
export WHISPER_CPP_MODEL="$HOME/.cache/whisper.cpp/ggml-tiny.bin"

# Python whisper 仅作兜底；默认 tiny / zh，避免 large/medium/turbo 阻塞任务
export DOUYIN_WHISPER_MODEL="tiny"
export DOUYIN_WHISPER_LANGUAGE="zh"
```

## 使用方法

### 方法一: 使用脚本 (推荐)

```bash
# 获取视频信息和下载链接 (无需 API 密钥)
python douyin_downloader.py --link "抖音分享链接" --action info

# 下载视频到指定目录
python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

# 提取视频文案并保存到文件 (优先 API/worker/whisper.cpp；最后 tiny 兜底)
python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

# 提取文案并同时保存视频
python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output --save-video

# 安静模式 (减少输出)
python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output --quiet
```

### 来源解析与下载失败处理（2026-10-09 更新）

用户指定复用已登录的现有浏览器时，先按已安装 `douyin-monitor` 的 `references/intake.md` 中 short-reading-route-and-desktop-fallback 小节读取已核验批次、实际作品类型/地址及现有连接；`DOUYIN_FORCE_PLAYWRIGHT=1` 不是新建独立浏览器的授权。已知图文作品保留原始照片序号，转入原图获取，不反复套视频下载/转写路线。明确取得真实公开媒体地址后继续下载与解码；桌面截图不记作原始媒体，连接故障不等于未登录。

先复用已经校验的本地媒体及仍有效的作者/作品记录。首次解析前检查实际使用的 Python 是否具备 `requests`；需要浏览器或解码时分别检查相应能力。缺依赖、内容连接断开、来源解析失败、媒体下载失败要分别记录，不因缺依赖自动安装或换浏览器。

当出现以下任一现象时，停止重复同一公共解析路线，保留失败阶段及已完成记录：

- `从HTML中解析视频信息失败`
- 页面没有 `window._ROUTER_DATA`
- 批量下载前几条成功，随后同一 IP/UA 连续失败
- M core/子 Agent 报 `iesdouyin 风控`

用户要求现有登录会话时，轻量视频解析可显式关闭独立浏览器兜底；使用已经验证可用的 Python 环境，并清除可能遗留的强制兜底变量。这个命令只解析已确认的视频，图文原图走独立采集分支：

```bash
# 已有登录会话：公共解析失败后交回受支持的现有页面读取，不另开浏览器
env -u DOUYIN_FORCE_PLAYWRIGHT DOUYIN_DISABLE_PLAYWRIGHT_FALLBACK=1 python3 ~/.agents/skills/seedance-douyin-video/scripts/douyin_downloader.py \
  --link "抖音分享链接" \
  --action download \
  --output "/目标目录"
```

下载器默认顺序：公开解析 → 复用已运行的Chrome取片，自动发现本机连接，只关闭本任务新建的标签页。公开页缺少媒体数据时由脚本直接衔接，正常任务无需另调浏览器控制工具。`DOUYIN_FORCE_PLAYWRIGHT=1` 仅保留为显式独立浏览器模式。

已有授权页面提供真实媒体地址时，优先直接消费该地址，并绑定作品ID、作者与照片序号。媒体地址可能有时效，应及时下载；长期记录保留作品链接、文件和校验值，不保存 Cookie 或带签名的临时地址。来源信息缓存和临时地址缓存分别处理。

下载前按作品ID复用输出目录或项目`outputs/intake`的原片；短链命中本地索引时也直接返回文件。首次发现原片核验一次，后续按文件字节复用。取片共用30秒预算，媒体下载只用一组请求头；地址失效时从现有Chrome刷新一次，再失败就返回当前阶段。成功文件直接交给拆解。

判断口径：
- 缺少 `requests`：运行环境问题，尚未请求作品；优先复用已有可用环境。
- 无路由数据或无法解析JSON：记录“公共页面解析失败”；可能是响应受限、结构变化或类型不匹配，单凭异常不能确定原因。
- 页面解析失败而受支持的授权页面可读取：记录两条路线各自结果，不自动断言平台接口变更。
- 所有当前媒体候选返回403/404/空文件：仅证明这些地址本次下载失败，不能确认作品删除、物理文件清理或账号退出。
- 汇报文件完成前核对作品绑定、媒体类型与解码结果。视频检查时长/分辨率及 `ffprobe`；原图检查张数/顺序及实际图像解码。3秒预览只记片段，不能直接记完整原视频；截图不能记原图。

### 输出目录结构

提取文案后, 每个视频会保存到独立文件夹:

```
output/
├── 7600361826030865707/      # 视频ID为文件夹名
│   └── transcript.md         # Markdown 格式文案文件
├── 7581044356631612699/
│   ├── transcript.md
│   └── 7581044356631612699.mp4  # 使用 --save-video 时保存
└── ...
```

### Markdown 文案格式

```markdown
# 视频标题

| 属性 | 值 |
|------|-----|
| 视频ID | `7600361826030865707` |
| 提取时间 | 2026-01-30 14:19:00 |
| 下载链接 | “标题 + 实际来源 URL” |

---

## 文案内容

(语音识别的文字内容)
```

### 方法二: 在 Python 代码中调用

```python
from douyin_downloader import get_video_info, download_video, extract_text

# 获取视频信息
info = get_video_info("抖音分享链接")
print(f"视频ID: {info['video_id']}")
print(f"标题: {info['title']}")
print(f"下载链接: {info['url']}")

# 下载视频
video_path = download_video("抖音分享链接", output_dir="./videos")

# 提取文案并保存到文件
result = extract_text("抖音分享链接", output_dir="./output")
print(f"文案已保存到: {result['output_path']}")
print(result['text'])
```

## 工作流程

### 获取视频信息

1. 解析抖音分享链接, 提取真实的视频 URL
2. 模拟移动端请求获取页面数据
3. 从页面 JSON 数据中提取无水印视频地址
4. 返回视频 ID, 标题和下载链接

### 提取视频文案

1. 解析分享链接获取视频信息
2. 下载视频到临时目录
3. 使用 FFmpeg 从视频中提取音频 (MP3 格式)
4. 优先调用硅基流动 SenseVoice API 或本地快速转写；无 API 密钥时走 worker / `whisper.cpp` / Python Whisper `tiny` 兜底
5. 清理临时文件, 返回识别的文本

## 常见问题

### 无法解析链接

- 确保链接是有效的抖音分享链接
- 链接格式通常为 `https://v.douyin.com/xxxxx/` 或完整的抖音视频 URL

### 提取文案失败

- 检查 `API_KEY`、`DOUYIN_API_KEY` 或 `SILICONFLOW_API_KEY` 环境变量是否已设置
- 确保 API 密钥有效且有足够的配额
- 使用本地路线时先运行 `fast_transcribe.py --diagnose`，按已配置后端分别核对环境和模型；不把worker离线一概解释为缺API密钥
- 确保 FFmpeg 已正确安装

### 下载速度慢

- 这取决于网络条件和视频大小
- 脚本会显示下载进度

## 注意事项

- 本工具仅供学习和研究使用
- 使用时需遵守相关法律法规
- 请勿用于任何侵犯版权或违法的目的

## 安装与迁移边界

脚本位于本Skill的scripts目录；文中 `~/.agents/skills` 是常见安装例，实际以当前Skill路径为准。基础下载需要Python 3、requests，解码需要FFmpeg／ffprobe；extract动作另需ffmpeg-python。浏览器分支按实际连接方式需要playwright／Chrome；独立浏览器必须是当前允许的分支。ASR只需要所选后端：已配置worker、whisper.cpp及模型、显式配置的faster-whisper环境及模型，或Python Whisper及模型；日常不自动安装/下载模型。明确的依赖维护任务可按授权准备必要依赖，不因此允许收费或上传。平台API需要其当前授权与注入凭据。

worker服务、模型权重、浏览器登录、原片、项目状态与主机配置不包含在Skill包中；仅下载或原片拆解不以ASR或工作台部署为前置。下载器extract和fast_transcribe共用同一本地后端选择，不再各维护一套默认。
