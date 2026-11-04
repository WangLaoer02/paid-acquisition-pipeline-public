# 荣耀HTTP上传扩展 1.3.1

默认复用HTTP上传服务，网站确实失效后沿该机器原自动或人工接码方式登录。全程不打开或连接浏览器。

本机已选人工短信的业务仍走原人工接码备用路径。正常业务读取不增加独立认证检查；广告GET被退回门户时只复用同一会话沿原生链接恢复一次，不提交登录或重试写入。1.3.0按本机授权把荣耀Cookie保存到macOS钥匙串独立会话条目，服务重启后先恢复，不能延长平台主动撤销的会话。旧进程仍须正常换版；部署与真实免登录恢复分别验收。

联合安装包包含rongyao-http-readonly 1.3.1、rongyao-http-upload 1.3.1，以及两个Skill的同源安装器。依赖本机已部署的现有rongyao-keyring原生助手、rongyao-operations和原买量管线runtime。安装不导入账号，不携带短信来源hash、验证码、Cookie、Token、运行账本或业务文件。新Mac的认证依赖和短信来源绑定遵循readonly README。

解压当前完整安装包后，先运行 paid-skit-progressive-setup/scripts/progressive_install.py verify，再按其plan和install --phase 5安装两个新Skill及原依赖。规则通过同包paid-skit-production-pipeline/scripts/deploy_workspace.py按原比较、备份机制同步到工作区。既有同源链接由维护部署保留；安装器遇到链接或差异会报告冲突，不盲目覆盖。原钥匙包源码不被持久改写。

入口：`python3 <扩展目录>/scripts/rongyao_upload.py start --output-dir <本次目录>`。后续status／fields／prefix／lookup均只读。submit必须给已登记原计划、原工作区及其单次票据；reconcile只回查原job。

该扩展共享原operations SQLite账本，禁止受理未知重传。第一次字节发送前即持久化selection_pending，网络异常保留submission_unknown。20MiB分片、原生合并字段来自当前官方表单，协议变化停止。上传服务与只读服务分别使用本机0700目录和0600 socket；认证Cookie保存到本机钥匙串，隐藏表单值只在内存。

用户默认：无明确需求人/制作编号来源时使用原创／D，明确来源优先。原创未在当前下拉中时，只在用户已指定且计划记录显式override时提交，并独立回读。AI不冒填无法对应的模型。

1.1.0：事务内内容／编号去重、显式来源归属继承、逐文件回执、失败阶段恢复和分层入库验收。升级须同步同版operations、工作区清单与安装包；旧服务进程必须正常重启。

1.2.0 增加独立主设计师证据、原 ID 归属收尾与十项可见业务字段验收。新命令与票据边界见 SKILL.md；reconcile 保持远端只读，归属收尾不重传视频。
