> 本机补丁 `0.2.0-rc.3+local.background-capture.2`：网页通过 `RONGYAO_CAPTURE_BACKGROUND=1` 使用不激活的后台查询标签；失效不自动打开登录窗，关闭本次临时页并返回提示；会话未运行或没有打开窗口时不自动启动或显示 Chrome。显式 `backend-login` 继续保留并前置登录页。其他调用仍保留登录错误窗口。

> 本机补丁 `0.2.0-rc.3+local.login-window.1`：登录失效时保留并前置登录页，新增 `backend-login`；不是未修改的上游版本。

# 运行依赖与离线校验

当前候选版为 `0.2.0-rc.3`，基于上游候选提交23d5af1并补齐抓取习惯、短期精确缓存、双区间并行与专用 Chrome 会话自动恢复；在新的跨平台CI通过前不得声称正式发布。四件套源码与验证工具分开，禁止把虚拟环境、后台快照、结果缓存或登录状态加入发布包。

## 解释器

- 分析/抓取脚本使用Python 3.10+。macOS系统python3可能为3.9，不因“命令存在”就认为满足要求。
- 已知可用解释器就直接复用。Codex Desktop可通过运行时依赖工具定位内置Python；不要每轮重新扫描。
- 维护测试可在 `$HOME/.codex/tools/rongyao-validation` 建隔离虚拟环境；当前机器已配置时优先用其 `bin/python`（Windows为 `Scripts/python.exe`）。可移植Skill不写用户绝对路径。
- PyYAML用于Skill格式检查，不是查询业务的依赖；cryptography用于合成加密回归与可选旧磁盘兼容路径。活动Chrome通道不要求解密Cookie。
- Node用于活动会话桥及合成桥测试；候选版CI基线为Node22，本机也可使用已通过自检的更新版本。

## 验证层级

1. 先运行 `scripts/validate_local.py`：检查四个Skill的元数据、内部引用、内置Python回归与活动桥离线自检。缺测试依赖时明确指出并使用隔离环境补齐；不谎报测试通过。
2. 完整候选版的77项基线还包含仓库根目录的产品、打包和Node故障注入测试，它们并不都在安装包内。只有确实运行该源码版本的完整测试才声明77项通过；内置回归数单独报告。
3. `scripts/package_bundle.py` 生成修复版无凭据白名单包；`scripts/install_bundle.py` 在空临时目标验证安装及回滚，不覆盖真实已安装Skill。
4. `material_performance.py run --period this-week --dry-run` 只生成具体计划，不访问后台、不创建输出、不写状态。
5. 用户要求的真实抓取成功且身份核验通过后才能说线上已实测；离线测试不证明登录、字段适配、导出或视频可播放。

测试脚本必须隔离自己的状态文件。新文件加入 `references/bundle-files.json` 后再打包；保留修改前备份，包版本标注local，不自动推送GitHub。

登录窗口回归：`node scripts/test_login_window.mjs`。成功/普通失败清理临时查询页；LOGIN_REQUIRED 保留用户登录页，仅断开协议连接。

## 本地引用的安装基准

`static_reference_check.py` 以调用路径的 Skill 安装根为逻辑命名空间；可显式传 `--skills-root /absolute/path/to/skills`。先在该命名空间中词法归一化 `.`/`..`，再打开文件；不先展开某个 Skill 软链接后把兄弟依赖解析到源项目旁边。执行者按输出 `resolved_references[].target` 的绝对路径读取，检查通过只证明本机文件存在，不证明宿主已重新加载或业务可用。

子目录软链接内的Markdown也按其逻辑安装路径扫描；循环目录别名报告未完成扫描，不静默跳过。内联与引用式Markdown链接（含完整、折叠、快捷标签）均检查其目标文件。

Markdown 链接及显式 `./`、`../` 相对当前文档；正文或命令里的 `references/`、`scripts/` 相对本 Skill 根；`skill-name/...` 相对所选安装根；包示例 `skills/<套件内名称>/...` 采用同一安装根。保留完整路径，不以别处同名文件兜底。URL与页内锚点不检查网络；文件加锚点仍检查文件，锚点标题不在本脚本验收范围。变量、通配符和占位路径列入 `skipped_references`，不冒称验证。可选旧助手仅由脚本中的“来源文档+完整路径”显式清单豁免，不豁免其他同名引用。

离线反例用 `python3 -B -m unittest discover -s scripts -p test_static_reference_check.py -v`；它只读写临时夹具，覆盖普通/软链接跨目录、缺失及无关同名、锚点、占位与可选依赖，并保留分析层不得采集、桥不得读凭据的检查。
