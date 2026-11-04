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

## 可执行补齐与来源锁

安装器主源是 `installer/scripts/progressive_install.py`，官方获取实现是相邻的 `official_dependencies.py`。固定来源、版本、下载 SHA256 和完整 Skill 目录摘要见 `installer/references/official-dependencies.json`；文件从官方直接下载到接收人的 `tool-root/official-cache`，不再分发官方包。HTTPS 校验始终启用；需要受信任证书时可传 `--ca-bundle`。网络失败不写半份 Skill，修复网络后原命令重试；缓存哈希不符或目标有手改时保留现场，选择新目录比较，不自动删除或升级。

### 飞书

官方 [larksuite/cli](https://github.com/larksuite/cli) 固定提交 `76f7e7eb92a511470b7a261ce8b82f9f4579d8c1`（package version 1.0.98），仓库 [MIT LICENSE](https://github.com/larksuite/cli/blob/76f7e7eb92a511470b7a261ce8b82f9f4579d8c1/LICENSE) 随每个下载 Skill 保留为 `LICENSE.upstream.txt`。只装四项，不递归启用引用中的可选白板等能力；实际需要其他 Skill 时按官方入口另装并验收。

```sh
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools official-install --provider lark
python3 installer/scripts/progressive_install.py --skills-dir ../my-agent-skills --tool-root ../my-tools tool-install-feishu
```

第二条在没有现有 CLI 时用 npm 官方包 `@larksuite/cli@1.0.98` 安装到隔离工具目录，保留 npm lockfile 中的解析版本与 integrity。已有 CLI 不升级/覆盖；输出路径必须供下游使用。基础 version 探测不证明文档/表格 shortcut 兼容；须核对 help/schema 后再使用自己的既有账号。原适配器曾使用 1.0.93，当前 1.0.98 的真实云端兼容性未验收。

### 国内即梦（默认）

本轮未取得可验证、允许公开自动下载的国内官方完整包。默认 `--dreamina-region cn` 报 `DREAMINA_CN_SOURCE_UNVERIFIED`；已有本机版本原样保留，来源/完整性/适配兼容仍待核验。向国内官方服务提供方获取适配当前账号的 CLI + Skill 完整包，保留其版本、校验文件和许可；在新目录按该包真实说明安装并核验 schema，不能猜 CDN 地址、复制作者的私有包或切换账号。此缺项不会被国际版消除。

### 国际 Dreamina（明确选择后可选）

[官方安装页](https://dreamina.capcut.com/ai-tool/install?from_page=explore) 提供 [安装脚本](https://dreamina.capcut.com/canvas-cli/install.sh)，本轮脚本指向 `1_0_0_29` 目录。固定 Skill 归档仅用于接收人本地安装，不推定有再次分发许可。官方页面的订阅、地区和服务资格独立核验。

```sh
python3 installer/scripts/progressive_install.py --skills-dir ../international-skills --tool-root ../international-tools official-install --provider dreamina --dreamina-region international
```

Skill 安装与 CLI 下载分开。仅 macOS arm64 的官方二进制在本候选固定哈希并做隔离基础执行检查；确需该国际版且没有已有 CLI 时，可在上一命令追加 `--with-cli`。发现 PATH 上已有 CLI 时保留并退出，不改 profile、不安装替代版本；其他平台返回未验证，按官方对应平台安装方式另行验收。汇总该路线时显式追加 `--dreamina-region international`；不能作为国内接入验收。

### 软件、环境与后续验收

FFmpeg/ffprobe 从上表官方渠道准备；Python 环境使用 `env-install --profile media|premiere|upload` 按当前阶段安装，保留现有锁文件与环境，失败后同命令续接。Premiere Pro/UXP、原生桥、宿主工具、可选 ASR 权重、账号权限和接收人规则发布是独立缺项；不通过 setup 自动购买、登录或发布。

`external_verified` 只表示文件完整且与固定官方来源一致。`external_present_unverified_or_modified` 表示现有版本不一致或手改，`external_conflict` 表示路径/链接冲突，`external_missing` 表示缺失。后三种均不能通过文件完成检查。`software_probe_passed` 仅版本执行与环境 import；`runtime_ready` 包括真实接口兼容与原生验收，`business_ready` 还需要自己的发布、当前项目、账号和授权，两者不由安装器赋真。

37 个随包 Skill 和 5 个外装依赖见 [分发清单](distribution.json)。来源核对日期：2026-11-04。隔离验证不等于 Windows、其他机器或真实生产验收。

国内来源恢复不是只复制文件：维护者需取得可合法使用的国内官方来源，核实地区与完整包后，在 `official-dependencies.json` 更新该 provider 的 region_code 为 cn、官方 URL/版本、archive SHA256、各 Skill tree_sha256 和已验平台二进制摘要；审查并重建新的公开版本后，在新隔离目录安装并复测。当前国际锁不接受国内目录作为已校验，不放开地区检查；没有上述新版本前国内 setup 保持退出 2。
