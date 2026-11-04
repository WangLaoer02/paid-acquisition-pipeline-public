# 荣耀无浏览器只读 1.3.1

默认：复用有效HTTP会话；需要认证时，现有Keychain账号＋Mac信息短信自动接收登录。用户不需要扫码或复制验证码。

## 安装

解压后运行 `python3 rongyao-http-readonly/scripts/install.py --destination <唯一源码目录> --register`。安装器把Codex和OpenClaw发现入口链接到同一源码；已有实体Skill目录会停止供检查，已有链接会更新。安装位置和Keychain位置按当前Mac用户解析，源码无个人Documents绝对路径。

自动接码机器已有的来源绑定和Keychain不随升级重置；源码中的验收记录不代表当前执行机器已经绑定。换电脑若继续使用自动接码，还需要已配置的 `~/.codex/skills/rongyao-keyring`、原受信任原生Keychain助手、Python3、Mac信息短信同步及执行进程的数据库只读权限。已选人工短信的业务继续原人工路径，不要求配置自动同步。安装器不导入账号、不授予系统权限、不启动浏览器。先检查 `keyring.py status`，不要因为历史缺项重复索要账号。

MacBook自动接码沿用户2026-10-23确认的60秒唯一新短信规则，不要求来源绑定。sms-bind仅保留历史元数据，不是登录前置；已选人工接码的Mac mini继续原人工/群备用入口。

## 使用

以下start是MacBook已采用的自动接码路径；Mac mini继续原人工/群备用。只在明确需要初始化且已授权时才使用后文initialize，不把start当两台机器通用的自动登录入口。

`python3 <源码目录>/scripts/rongyao_http.py start --output-dir <本次结果目录>`

start先复用有效服务；服务退出或重启后先从本机钥匙串恢复并验证保存的会话；没有有效保存会话才沿本机原短信方式认证。成功返回session_id。随后用同一CLI的 `video-list --session <ID> --output <文件路径>` 读取首页。`status`发现服务，`stop --session <ID>`结束它。服务进程单次最长24小时；保存的会话不因此丢失，恢复仍受网站有效期约束。

MacBook自动短信等待最多60秒；超时、权限拒绝、多个候选、原生助手结构变化和登录拒绝均停止，不自动重试发送或切换扫码。`--new-session`仅供明确要求完整新登录验收时使用，日常执行不使用。

## 认证与恢复

原生助手固定消费进程临时增加一次性HTTP分支，导入后立即恢复原worker和CLI；启动器finally再次恢复并移除临时模块。临时源码备份位于本机0700目录，文件0600，只是源码，不含凭据。KEYRING_STRUCTURE_CHANGED或PENDING_LOCAL_OTP_WORKER应先检查源码及待处理状态；不盲目覆盖并发修改。

短信来源配置、验证码、密码、Cookie、数据库、业务列表及运行会话都不在包中。Cookie只通过独立原生助手保存到本机macOS钥匙串，不写明文文件；服务重启后可恢复，平台撤销或过期仍须正常认证。当前只验证未筛选视频列表首页。

1.2.0新增可明确选择的独立HTTP上传服务启动接入；只读服务保留原命令及限定query、weekly/market模块，提交由独立上传Skill及原runtime守卫处理。

1.3.0新增独立会话存储助手：`python3 scripts/session_store.py build`只在启用该功能时构建一次，不重建原密码助手。之后原业务命令在找不到服务时自动恢复，不增加日常检查。`session_store.py status --service upload`仅显示保存状态；`forget`清除该范围保存的会话；`restore --output-dir <目录>`不发码。首次明确初始化可用`initialize --output-dir <目录>`，仅这一次在本机隐藏输入窗口完成原账号短信认证，不创建上传批次。原群人工备用与另一台Mac自动接码路径保留。

跨机器不复制Cookie；纯SSH钥匙串-25308应保留现场，在本机已登录用户桌面环境恢复，不解锁或改ACL，不误判为网站过期而发码。
