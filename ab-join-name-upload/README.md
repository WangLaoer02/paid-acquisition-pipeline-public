# 接B · 命名 · 上传清单（Codex Skill）

做完 A 段后，让 Codex 自动：从选B台挑 3 段合适的 B → 下载并校验 → FFmpeg 接片 → 技术核查 → 按团队命名规则命名 → 生成后台上传清单。**只在本机处理文件，不登录、不上传**；上传由本人在自己的后台账号完成，之后可把素材 ID 回填到本机台账。

> 本目录是公开源码，**不含团队配置**（人员代号表、后台字段可选项、选B台地址）。团队配置由负责人单独发放，用 `import-config` 导入。请勿把团队配置提交到本仓库。

## 安装（Mac）

需要：Codex（本人账号）、Python 3.9+、FFmpeg。

```bash
git clone https://github.com/WangLaoer02/paid-acquisition-pipeline-public.git
```

```bash
cd paid-acquisition-pipeline-public/ab-join-name-upload
```

然后双击 `双击安装.command`（或运行 `bash install.sh`）。把负责人发的 `团队配置*.zip` 放在“下载”文件夹里，双击安装会自动导入；也可以手动导入：

```bash
python3 ~/.codex/skills/ab-join-name-upload/scripts/abtool.py import-config --from ~/Downloads/团队配置.zip
```

以后更新：在仓库目录 `git pull`，再双击安装一次（已有配置会保留，变更前自动备份）。

也可以直接让 Codex 安装：

```text
从 https://github.com/WangLaoer02/paid-acquisition-pipeline-public 拉取 ab-join-name-upload，运行里面的 install.sh 安装技能，再用 import-config 导入我“下载”文件夹里的团队配置 zip，最后跑 doctor 告诉我结果。
```

## 使用

见 [同事使用说明](同事使用说明.md)。核心命令：

| 命令 | 作用 |
|---|---|
| `run` | 一条命令：自动选 B → 下载校验 → 接片 → 核查 → 按连续序号命名出清单 |
| `record` | 上传后回填素材 ID 到本机台账 |
| `import-config` / `set-library` | 导入团队配置 / 更新选B台地址 |
| `doctor` / `ledger` | 环境检查 / 查看本机台账 |

## 测试

```bash
cd skill/ab-join-name-upload && python3 -m unittest discover -s tests
```

测试使用 `tests/fixtures/team-config` 里的虚构配置，不访问任何真实服务。
