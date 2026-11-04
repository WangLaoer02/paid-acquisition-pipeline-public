# 短信自动登录合同 1.1.0

默认路径：本机有效HTTP服务 → 现有Keychain账号＋本机Mac信息取码 → 直接HTTP视频列表。不请求用户扫码。

1. 启动前检查短信数据库只读访问、原钥匙包助手及CLI/worker结构。只用原账号，原生助手注入RONGYAO_USERNAME及RONGYAO_PASSWORD到一次性固定消费进程；模型和父进程不接收凭据。
2. 在请求前记录消息最大ROWID及当前时间。同一内存CookieJar先GET荣耀门户，再POST `/?_c=login&_a=sendMessage`，表单仅username。受理必须status=true或1；未知结果不重发。
3. 用户2026-10-23修订：不校验发送号码hash，不限制炽焰网络或后台验证码文字。只查询本次发码后0至60秒内、ROWID晚于请求前基线的入站新短信，提取独立六位数字。唯一候选码使用；不同候选码冲突时停止。相同码的重复短信取最新记录。超时不重发，不输出或落盘验证码。
4. 仅向原门户POST `/?_c=login&_a=login`，表单username/password/code/token为空字符串。仅提交一次；验证码随即删除变量。认证失败停止。
5. 跟随受理返回的正常门户URL，再读取真实广告后台入口链接，GET视频列表。HTTP登录transport只接受荣耀门户和广告后台的HTTP主机，POST进一步限定门户登录动作；禁止外部主机、userinfo及广告后台POST。
6. 登录成功删除凭据环境变量，将有效Cookie通过固定原生助手安全写入本机Keychain，再启动可复用服务。状态authentication_method=existing_keychain_password_and_fresh_sms，feishu_qr_authenticated=false。默认最多24小时且网站有效期优先。
7. 源码安装与发布只含程序、说明及脱敏验收统计。短信发送方hash只留本机state；sms-bind仅保留历史来源记录，不作自动接码前置；新机器不自动导入账号。

保留的[飞书二维码诊断合同](legacy-feishu-qr.md)只在用户明确要求时使用，不是默认或失败回退。
