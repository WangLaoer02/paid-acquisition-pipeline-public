# Chrome会话维护

只用于已选Chrome查询/视频分支；普通素材HTTP及上传不读本参考。登录决策由已安装的 `rongyao-keyring` 统一维护。已配置钥匙包时直接调用原执行器内的固定助手；系统权限、验证码和明确拒绝按其合同停止。以下人工步骤仅用于未配置自动登录且用户明确初始化的机器。

- 看到“登录态失效、没有目标域 Cookie、无法复用 Chrome 登录态”时停止查询。
- 提醒用户在 Chrome 打开 `http://power.houtai.backend.example.invalid/` 并手动完成登录。
- 用户完成实际页面验证后继续原任务；同版环境已就绪不重复整个预检，已提交失败的查询不重放。
- 不读取键盘输入，不保存密码，不把 Cookie 写入 Skill 或迁移包。

### 专用活动会话（macOS / Windows）

当后台使用仅存在于 Chrome 进程内的会话 Cookie 时，不再关闭 Chrome 或读取磁盘 Cookie。运行：

```powershell
python "$env:USERPROFILE\.codex\skills\rongyao-data-stack\scripts\active_session_cli.py" backend-open
```

该命令首次启动独立的荣耀 Chrome 配置。已配置钥匙包时由固定助手核验并按需恢复登录；未配置的初始化环境才由用户在正常页面完成登录。之后复用同一配置；仅专用进程确实退出才恢复，活动进程连接不明时停止。状态文件只保存专用 Chrome 的 PID、本机 DevTools 端口、配置路径和时间，不保存 Cookie、Token、密码或浏览器存储。

可主动保证会话存活（日常查询已自动执行，通常无需手工调用）：

```powershell
python "$env:USERPROFILE\.codex\skills\rongyao-data-stack\scripts\active_session_cli.py" backend-ensure
```

只读检查会话：

```powershell
python "$env:USERPROFILE\.codex\skills\rongyao-data-stack\scripts\active_session_cli.py" backend-status
```

一次查询结束前不要关闭专用 Chrome。闲置时可关闭，下次查询会使用同一配置自动恢复。

