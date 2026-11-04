# 活跃 Chrome 会话直连

仅在主Skill已选Chrome兼容入口、或HTTP适配器不支持的项目/维度需要该桥时读取。登录决策统一按已安装的 `rongyao-keyring`；磁盘Cookie不是默认入口，HTTP失败不自动切换Chrome。

## 前置条件

1. macOS / Windows 默认由 `readonly_capture.py` 自动复用或重启凭据隔离的专用 Chrome 配置；也可手工运行 `active_session_cli.py backend-ensure`。
2. 本机已有钥匙包时由原执行器内固定助手恢复，不要求用户手动登录；只有未配置的初始化环境才在正常专用窗口人工登录。已退出的专用进程可恢复同一配置，活动进程连接不明时停止。
3. 活动会话桥只保存 PID、本机 DevTools 端口、配置路径和时间；不得读取或保存 Cookie、Token、密码或浏览器存储。
4. 不读取、打印、保存或传输 Cookie、Token、密码、Local Storage 或 Session Storage。

## 直连原则

- 在已登录目标页的同源上下文中，复用浏览器自动附带的 HttpOnly/会话 Cookie。
- 调用与 `rongyao-data-stack/scripts/backend_export_cli.py` 相同的页面配置、查询和导出接口；接口结果是唯一数据源。
- 不从可见表格抄录数据，不进行分页抓取，不把 DOM 行当作后台完整结果。
- 查询固定 `date_group=tenyear`、`group=mid`、`source_video_type=1`、`filter=1`，并验证 gid、投放日期、素材产出日期与导出 CSV。
- 普通独立对比最多2路并发；高成本素材编号查询保持单路。禁止查询提交后自动重试或任何后台写操作。

## 执行顺序

1. 运行 `active_session_cli.py backend-status`，确认专用会话存活；状态检查不得触发后台数据查询。
2. 通用查询由 `readonly_capture.py` 创建轻量同源页；素材表现 CSV 由 `backend-export` 创建同类页面。两者都先确认没有跳转登录页。
3. 在真实页面上下文请求当前 `market` 页面 HTML，解析 `_pageConfig`、`_initRand` 与 `_getDataUrl`；浏览器隐式附带会话，助手不读取凭据存储。
4. 按 `backend_export_cli.py` 的 `backend_default_search()` 规则构造查询；如页面默认筛选包含 `operation_client`，先调用 `ApiGetPcidList.php` 获取 pcid。
5. 向 `_getDataUrl` 发送同源只读查询，要求 JSON `status=true` 并取得服务端返回的 `rand`、`count`、`totalpage`、`pagesize`。
6. 汇总/筛选查询直接返回 `info.sum`、受控分页行和 `rand` 指纹；素材表现需要 CSV 时才请求 `ac=export&rand=<rand>`。若返回HTML、登录页或非预期响应立即停止，区分认证、协议与结构错误；不把所有非预期响应统称掉线。
7. 将 CSV 直接写入本次输出目录，再运行 `material_performance.py analyze`；不得把凭据或完整素材地址写入状态文件。

## 失败处理

- 页面不存在或未登录：在业务查询发送前，按钥匙包合同恢复原专用入口；真实验证码、系统拒绝或权限不足分别报告。
- 专用会话不存在或进程已退出：查询前自动用同一配置恢复，不要切换日常 Chrome Profile。
- 自动恢复后仍跳转登录页：报告该入口认证未通过；已发送的查询不重跑，尚未发送才可在认证明确成功后执行原请求一次。
- DevTools 只绑定专用 Chrome 配置和本机回环地址；不得附加用户日常 Default Profile。
- 查询超时、504、字段或项目身份不符：停止，不连续重试，不把缺失当 0。
