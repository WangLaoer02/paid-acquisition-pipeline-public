# 公开版安装汇总

源码根目录先读 README.md 与 docs/dependencies.md。独立安装器使用：

```sh
python3 scripts/progressive_install.py --skills-dir ../my-skills --tool-root ../my-tools setup --phases 0 --backend dreamina --with-official-skills
```

切换所需阶段，或显式 `--phases all`。退出 2 必须读取 steps/missing 并补齐后同命令重试；`install` 的复制结果不等于完成，doctor 2 不得忽略。退出 0 仅所选阶段文件与软件基础探测通过。runtime_ready/business_ready 始终未验收，不登录或调用业务。

`official-install --provider lark` 从官方固定提交安装四 Skill 并保留 MIT；`tool-install-feishu` 在缺现有 CLI 时安装隔离 npm 1.0.98。`env-install --profile media` 或 premiere/upload 按需安装独立环境。来源/版本/哈希见同目录 official-dependencies.json；账号、CLI shortcut 兼容、FFmpeg、Premiere/UXP/桥、宿主工具、模型与业务授权另外核验。

国内即梦默认 `--dreamina-region cn`：本轮未核实可公开自动下载的国内完整包，必须列缺项并向国内官方取得；不复制作者包或切账号。国际官方路线只有显式 `official-install --provider dreamina --dreamina-region international` 才下载 Skill；`--with-cli` 仅支持已固定哈希的 macOS arm64 二进制，保留已有 PATH CLI。汇总国际路线同样显式传地区；国际可用不代表国内可用。

存在完整官方文件与固定摘要一致才为 external_verified。空 SKILL.md、不同版本、手改或链接均保留并报告未通过。在新的 skills-dir/tool-root 比较，不自动升级、删除或覆盖。下载仅 HTTPS，失败不写半包；恢复网络后原命令续接。缓存不符或哈希变化停止，维护者核对新版本后才能更新锁。

国内来源恢复不是只复制文件：维护者需取得可合法使用的国内官方来源，核实地区与完整包后，在 `official-dependencies.json` 更新该 provider 的 region_code 为 cn、官方 URL/版本、archive SHA256、各 Skill tree_sha256 和已验平台二进制摘要；审查并重建新的公开版本后，在新隔离目录安装并复测。当前国际锁不接受国内目录作为已校验，不放开地区检查；没有上述新版本前国内 setup 保持退出 2。
