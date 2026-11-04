# 已观察的无浏览器认证合同

1. 直接读取荣耀门户，核对现有飞书应用 `cli_a19268d41e78d00d`。正常 OAuth 入口是 `https://open.feishu.cn/open-apis/authen/v1/index`，回调固定为荣耀门户 `/api/ApiFeiShuRedirect.php`；状态为原页面的login，不将回调改成本机或其他应用。
2. 跟随官方HTTP重定向到accounts.feishu.cn，保留本次内存CookieJar。POST `/accounts/qrlogin/init`，JSON为当前OAuth的redirect_uri。读取原页面取得的CSRF Cookie，通过X-Csrf-Token提交；携带X-Flow-Key并按响应更新。
3. 当前网页接口版本头为 `X-Api-Version: 1.0.31`，`X-App-Id: 12`，终端类型2。X-Device-Info沿页面结构填写程序自身设备信息，device_name非空。原400分别返回“header 'X-Api-Version' is needed”“header 'X-Device-Info' is needed”“device_name cann't be blank”；仅HTTP200仍可能有业务code4401，必须code0。
4. 二维码内容与官方页面一致：JSON对象qrlogin.token。原生扫码token不是OAuth code，也不是CLI用户Token。用本地lark-cli auth qrcode生成唯一PNG；不通过第三方二维码服务。QR轮询 `/accounts/qrlogin/polling`：状态1等待、2已扫待确认、3取消、4错误、5过期。成功next_step为enter_app。实测约60秒过期，持续轮询不承诺延长有效期。
5. 按enter_app实际返回的mode、cross_login_uri、local_login_uri完成官方跨域跳转；当前实测为redirect。URI与Cookie只在内存。再次读取OAuth页，解析window.serverInjectRes的应用、身份、scope与X-Auth-Flow-Key，不输出其原值。
6. 当前授权页version=v1、应用“荣耀游戏”，历史权限auth:user.id:read，新增权限为空。POST `/open-apis/authen/v1/confirm`，JSON包含app_id、user_id、scope；认证页的open_csrf_token作为open-csrf-token头，携带X-Auth-Flow-Key。只处理原页面对应的既有权限；未知受理不能重复确认。
7. code0后由同一程序跟随实际redirect_uri，荣耀服务端建立门户会话。读取门户实际广告后台链接进入adopenplatform，然后GET `/app/data/?_c=jrttList&_a=index&ac=jrttVideoList`。这是直接HTTP读取服务器生成HTML，不宣称有官方JSON业务API。
8. 只处理HTTP Location重定向。列表页内可能含点击事件的location.href，不能把任意脚本中的该语句当成立即跳转，否则会循环读错页面。按卡片中的id[]与唯一text名称输入配对，并核对视频数量总数。

本路径与已有Chrome、飞书CLI和上传器是不同会话。新电脑无登录态；源码包不含账号密码、Token、Cookie、二维码、运行台账或业务列表。新会话扫码要实测，不能用旧会话复读替代。
