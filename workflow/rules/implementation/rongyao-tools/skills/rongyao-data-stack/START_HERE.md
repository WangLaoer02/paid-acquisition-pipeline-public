# 荣耀只读抓取入口

新素材2.0查询、导出和分析统一读rongyao-dashboard-filter-finder；rongyao-material-performance是兼容名称与共用脚本。普通素材CSV在本机默认HTTP；跨项目、编号及额外维度的Chrome桥才使用 `scripts/readonly_capture.py`。解释判断使用rongyao-material-analysis。登录恢复以已安装的rongyao-keyring为唯一合同。

底层查询必须收到具体项目、投放日期、素材产出日期；用户自然语言可按 references/capture-habits.md 解析，不要求重复手填可解析参数。全项目请求先列出可见、已查、排除、失败项目；固定别名只是入口映射。失败保持 missing；没有匹配不等于历史未做过。所有日期示例只说明格式，不是最新后台默认值。

```sh
python scripts/readonly_capture.py query --date-range 2020/01/01-2020/01/01 --material-range 2020/01/01-2020/01/01 --gid 90001 --transport active --retries 0 --output result.json
```

查询提交后不自动重试，也不跨通道重放。批内元数据缓存最多64项；`--output` 是用户指定的本地结果文件，禁止提交到源码仓库。高成本素材编号单请求、单并发，后续页复用 rand；分页失败不作为完整明细报告。未知完成状态先核查，不另起命令重放。

## 登录与冒烟

首次安装或诊断时运行 scripts/preflight.py 区分分析能力、传输环境和登录验证；默认不读取磁盘Cookie。日常已有环境时直接执行用户已授权查询；HTTP执行器复用服务或本机Keychain，Chrome分支才复用原专用配置，不另发登录探测查询。已配置钥匙包时服务端会话过期由固定程序正常恢复，不重复询问授权；未配置时才进入初始化或人工分支。成片上传直接转rongyao-operations最短路径，不以查询登录/冒烟作前置。不索取密码、不导出 Cookie。

只有用户要求独立冒烟验收且已确认登录后，才做一次单日单项目汇总冒烟；它不是日常抓取的前置步骤：

```sh
python scripts/live_regression.py --login-confirmed --date-range 2020/01/01-2020/01/01 --material-range 2020/01/01-2020/01/01 --gid 90001 --output smoke.json
```

替换合成日期和项目为当前授权范围；该命令不做素材编号查询、不下载、不查询历史控制月。无登录确认只输出 blocked。URL提取/访问/播放状态分开，冒烟不证明视频播放能力。

## 打包与安装

scripts/package_bundle.py 只打包 references/bundle-files.json 白名单。scripts/install_bundle.py 支持校验、安装、升级前备份与回滚；默认只预览，写入需要 --apply，已有目标需要 --replace。完整说明见 references/portability.md。
