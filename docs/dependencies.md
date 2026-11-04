# 依赖来源和真实可用边界

| 依赖 | 分发方式 | 接收人动作 |
|---|---|---|
| 项目工作流、节点、规则、执行器和项目自有 Skill | 随源码；项目自有内容 MIT | 保留 MIT 声明；第三方原许可分别保留 |
| imagegen | 保留 Apache-2.0 LICENSE.txt | 仍需可用的宿主工具或本人 OpenAI API 权限 |
| seedance-cinematic-director | 保留 MIT 许可与 wangzhang-wu 署名 | 部分内容有本地修改，不冒称上游原版 |
| lark-doc / lark-sheets / lark-drive / lark-shared | 原厂全文不再分发 | 从 [larksuite 官方仓库](https://github.com/larksuite/cli) 安装 CLI 和 Skill |
| Dreamina Canvas CLI 与官方 Skill | 不打包二进制或原厂 Skill | 从 [官方安装页](https://dreamina.capcut.com/ai-tool/install?from_page=explore) 取得本地区/账号可用版本；国内外服务与账号不混用 |
| Node.js | 外部软件 | [Node.js](https://nodejs.org/)；运行前检查适配器声明的最低版本 |
| FFmpeg/ffprobe | 外部软件 | [FFmpeg 官方下载](https://ffmpeg.org/download.html)；遵循所用构建的许可 |
| Premiere Pro / UXP Developer Tool | 外部商业软件 | [Adobe 官方开发文档](https://developer.adobe.com/premiere-pro/uxp/)；安装本仓库桥只提供接口，不提供软件授权 |
| Python 包 | requirements 按阶段列出 | 在独立虚拟环境按需安装；不随仓库拷贝 site-packages |
| 参考媒体、角色、字体、音乐、ASR模型 | 不包含 | 接收人提供有权使用的来源；转写按实际需要安装模型 |
| 荣耀企业服务 | 企业可选适配器源码 | 原私有地址替换为 `.backend.example.invalid`；接收人管理员提供自己的端点与权限，并独立验收 |

官方飞书仓库目前公开的安装入口：`npx @larksuite/cli@latest install`，随后按官方 Skill 配置本人应用、登录并查询状态。本项目既有适配器曾以 1.0.93 的 shortcut 合同运行；官方最新版兼容性必须按目标机器验证，不因安装最新版自动标通过。安装器自带 `tool-install-feishu` 保留该固定版本入口且不会覆盖已有 CLI。

Dreamina 安装页提供平台专用安装方式，使用本地区官方服务返回的版本与安装包。不存在已确认的国内通用安装地址时，向该服务提供方取得；不猜测 CDN 路径，不把国际账号切换成国内账号。官方 CLI 的 `schema`、身份与实时模型目录是调用依据。取得 Skill 文件不等于取得模型、会员或积分。

37 个随包 Skill 和 5 个外装依赖逐项列于 [分发清单](distribution.json)。原包中的历史图库、真实案例媒体、私有生产数据与原厂许可未知全文不分发。可选方法仍保留依赖说明；缺失条件应停在对应动作，不能以占位成功继续。

来源核对日期：2026-11-04。网页来源只证明官方获取入口，不证明本机或接收人的账号可用。
