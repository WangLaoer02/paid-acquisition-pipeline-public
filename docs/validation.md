# 验证范围（2026-11-04）

公开版在独立目录中验证，不使用作者账号进行生成或业务上传。下面区分真实本地执行、协议模拟和未覆盖项目。

| 项目 | 验证方式和边界 |
|---|---|
| 空工作区初始化、重复初始化保护 | 从公开清单复制到不存在的新目录；项目绑定为空；已有目录拒绝覆盖 |
| A01/A02/A03与全部24节点 | 实际运行离线 context 及节点/条件路由验证；不推进线上状态 |
| 配置与生产守卫 | 未配置拒绝生产；本地配置与业务状态不参与源码漂移判断；安全配置另由线上marker固定 |
| 受管源码和Skill篡改 | 调用真实完整性/生产检查代码；用模拟飞书marker证明修改受管代码、Skill或安全配置被拒绝；未向真实租户发布 |
| 安装 | 独立目录实际安装 bootstrap、0、1、2、4（Dreamina）、6、7；官方外装依赖明确列为未安装；同名手改拒绝覆盖 |
| 媒体依赖 | 独立虚拟环境实际安装锁定依赖并通过导入/FFmpeg检查；本机Python默认CA失败后显式使用系统 `/etc/ssl/cert.pem`，未关闭TLS验证 |
| 页面 | 真实Chromium点击6卡、18个可见二级入口、25个深链（保留合并别名），上一/下一、关闭/Escape、焦点返回通过；已看截图；仅favicon请求404 |
| 提示词/来源/分镜/顺序/上传守卫/PR桥 | 本地回归验证；PR桥使用测试宿主，不代替接收人真实Premiere打开、保存和导出 |
| 分发内容 | 逐包审查原42归档；公开37包，5原厂外装；全量递归扫描外层和ZIP成员、哈希、路径/链接及大文件 |

复验入口：

```sh
python3 tools/public_release.py verify
python3 -m unittest discover -s tests -p test_public_portability.py
python3 scripts/workflow_node.py validate
```

公开版源码树中不含作者维护发布历史、机器基线和云端旧部署回归；相关历史测试未分发，其公开版替代验证在 `test_public_portability.py`。实际发行清单为 `PUBLIC-MANIFEST.json`；Skill清单为 `SKILLS-MANIFEST.json`；安装归档内容与哈希由 `installer/manifest.json` 固定。

未覆盖：接收人飞书登录与真实规则发布、正式项目Sheet写入、即梦真实身份/报价/付费生成、团队或带参考图模式、真实Premiere原生导出、实际荣耀企业服务与视频上传、Windows/Linux原生流程、GitHub Pages。Canvas受管适配器目前只支持个人账号、单输出、无引用t2v；缺少账号时不会把离线准备称为生成通过。完整成片的音画、审美与逐镜分镜对应仍需具体生产任务验收。
