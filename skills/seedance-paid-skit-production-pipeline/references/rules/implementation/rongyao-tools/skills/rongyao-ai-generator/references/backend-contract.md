# 后台接口与 CLI 契约

来源：2026-10-05 在已登录 Chrome 中保存的页面模型配置、`ai_model_chat.js`、`aiMediaOptionControls.js`。这些是公司前端观察到的接口，不是厂商 API 稳定性承诺。

## 路由

固定主机 `http://ai.cn.sy.backend.example.invalid`，接口路径 `/data/?_c=aiModel&_a=ACTION`。页面 fetch 使用同源登录态；失败不换账号或跨通道重放。

| CLI | ACTION | 方法与主要字段 |
|---|---|---|
| status / sessions | sessions | GET；data.sessions |
| quota | quotaSummary | GET mode=chat/image/video，detail=1 读取明细 |
| session | sessionDetail | GET chatid；data.messages、parent_ids、page |
| messages | sessionMessages | GET chatid、before_id、limit |
| task | taskStatus | GET task_id；data.status、progress、images/videos |
| assets | assetList | GET favorite_filter、media_type、model_key、owner_scope、day_window=1、day_offset、day_size |
| subjects | subjectList | GET scope=self/public、keyword、page、page_size |
| voices | audioCloneList | GET keyword、status、visibility、page、page_size |
| tts-history | audioTtsHistory | GET page、page_size |
| upload | upload | POST multipart：file、type=Chat/Image/Video、model |
| submit | send | POST JSON，下表参数；默认不发送 |
| download | downloadMedia | GET url、name，触发浏览器下载 |

返回通常为 `{ok, data, error, code}`。图片/视频提交保留 `task_id / chatid / record_id / generation`；异步聊天可能返回 `mode=async`。任务 `done` 后仍需核对输出 URL 和下载文件。

## 生成请求

| 类型 | 字段 |
|---|---|
| 共用 | type、mode、model、chatid、parent_ids、message、attachments、attachment_ids |
| 图片 | prompt、size、ratio、resolution、n、quality、output_format、background、image_ratio、intelligent_ratio、prompt_optimize、subject_refs |
| 视频 | prompt、video_mode、seedance2_mode、ratio、resolution、duration、n、generate_audio、prompt_optimize、subject_refs |

`attachments` 为后台上传结果对象列表，`attachment_ids` 同序；`subject_refs` 从主体库对象提取 `id / subject_name / subject_desc / images`，每个主体最多 4 张图片，兼容 `img1` 至 `img4`。图片默认开启提示词优化，可加 `--no-optimize`；视频音频按所选模型默认值，也可显式 `--no-audio`。CLI 不给出未经核验的单价，计划内 estimated_cost=null。

## 主要模型键

| 模型 | 完整键 | 观察到的主要限制 |
|---|---|---|
| Grok 4.6 | xai_grok_4_6 | 聊天，最多 3 张图 |
| 豆包 Seed 2.0 | doubao_seed_2_0 | 聊天，最多 3 张图 |
| GPT Image 2.5 Fast | gpt_image_2_5_flare | 最多 10 张参考图、10 张输出；含 4K 尺寸 |
| GPT Image 2.5 精确 | gpt_image_2_5_sunburst | 同上，独立模型键 |
| GPT Image 2 | gpt_image_2 | 1024 方形或 1024/1536 竖横、auto |
| Grok Image | xai_grok_image | 1k/2k，最多 4 张图 |
| 即梦图片 4.0/4.1/4.5/4.6/5.0 | jimeng_*_official | 1k/2k/4k，1 张输出 |
| Seedance 2.0 自接 API | bytedance_seedance_2_0_ark | 480p/720p，自动时长 -1 或 4–15 秒 |
| Seedance 2.0 Fast | bytedance_seedance_2_0_fast | 480p/720p，自动时长 -1 或 4–15 秒 |
| Seedance 2.0 七牛 | bytedance_seedance_2_0 | 720p/1080p，4–15 秒 |
| Seedance 2.0 拼框 | bytedance_seedance_2_0_pinkuang | 480p/720p/1080p，4–15 秒 |
| Seedance 2.0 Mini 拼框 | bytedance_seedance_2_0_mini_pinkuang | 480p/720p，4–15 秒 |

Seedance 2.0 全能模式上限为 9 图、3 视频、3 音频；视频 50MB、音频 15MB。首尾帧模式只用首、尾两张图片，忽略视频/音频引用；CLI 遇不兼容附件直接报错，避免静默丢素材。更多 Seedance 1.0/1.5、Grok、即梦视频参数通过 `models --type video` 或 `models --key KEY` 查看。

页面还提供隐藏专用模型：图片去背景、改尺寸、压缩、合成、视频超分。它们需要专用字段，目前不通过普通 `plan` 冒用。

## 独立界面与未封装的操作

- AI 画布：`/data/?_c=aiCanvas&_a=index`；其独立前端与接口尚未建立 CLI 契约。
- 更多菜单：素材分析 `materialAnalysis/index`、第三方费用 `thirdPartyUsage/index`、配置 `index/index`。
- 声音克隆：`audioCloneSubmit` multipart、`audioCloneDetail`、`audioCloneDelete`；TTS `audioTtsSubmit` JSON、`audioFishPublicModels`。当前只封装已有声音和 TTS 历史查询。
- 主体：`subjectSave / subjectUpdateSettings / subjectDelete / subjectHistoryImages / subjectTagList / subjectTagSave`。
- 会话/素材：`renameSession / deleteSession / cancelGenerationTask / favoriteSave / favoriteDelete / favoriteCheck / videoFirstFrame`。

上述入口来自源码观察；未执行的外部写入不能写成已验证。不要通过通用请求接口猜参数。
