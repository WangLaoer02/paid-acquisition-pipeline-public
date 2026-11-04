---
name: rongyao-operations
description: "荣耀后台计划与账本 CLI：检索新素材2.0、生成已验成片上传计划、检查计划SHA和原job状态，并按原transport路由回查。默认HTTP提交转同级rongyao-http-upload；Chrome上传仅用户明确选择时使用。A/B制作和广告计划发布不在本技能范围。"
---

# 荣耀后台操作：计划、账本与命令路由

本机入口 `rongyao`；不在PATH时用 `python3 ~/.codex/skills/rongyao-operations/scripts/rongyao.py`。账号复用与登录恢复按已安装的rongyao-keyring唯一合同，不预跑通用Chrome登录检查，不创建账号/密码副本；同一账号任务已有正常登录授权不重复询问。缺文件先查access目录和当前任务产物，不用历史素材补测试。

| 本次动作 | 执行入口与边界 |
| --- | --- |
| 已验文件默认HTTP上传 | 直接读取 [HTTP提交与恢复合同](../rongyao-http-upload/SKILL.md)，从现有job或新计划继续；无需先读material-upload全文。命名、归属或制作验收未明确时才读该专项对应段。 |
| 创建计划、检查计划、查原job | 本CLI的 `video plan`、`video inspect-plan`、`job status`；这些动作不授予提交权限。 |
| 续接待核对job | 先读原回执transport：`direct_http_sms`用HTTP执行器 `reconcile --job-id`，明确Chrome作业才用本CLI `job reconcile`；来源不明先定位，不切换或重传。 |
| 明确Chrome兼容上传 | 按 [兼容提交合同](references/cli-contract.md#chrome兼容提交合同) 使用 `video upload`；该命令不会自动转HTTP，HTTP失败也不自动转Chrome。 |
| 明确原生辅助功能选框 | 读取 [原生恢复合同](references/native-recovery.md)，使用当前发布的native-plan/native-upload；不重放历史项目助手。 |
| 新素材2.0、视频检索与关键帧 | `video search / resolve / frames`沿原只读链；search和list只覆盖第一页，不能冒充全量台账。缺实际枚举时，HTTP用其fields，显式Chrome才用本CLI `video fields`。 |

## 计划与账本

已有登记计划及文件未变则复用，不重新命名、解码或建job；只有新文件或已证明未发送且明确采用的纠正才生成新计划。完整清单、参数覆盖与命名副本见 [命令与清单](references/cli-contract.md#命令与清单)。需A/B加工时先按 `../rongyao-video-upload/SKILL.md` 完成制作与正式命名；独立完整成片不虚构A/B来源、37分成或管线item。

`plan`仅完成本地技术检查和参数分组，不证明字段有效、后台无重名或画面通过；`test_only:true`永不允许外部上传。`inspect-plan --plan <原计划> --workspace <工作区>`返回input_sha256，由原runtime把本次真实上传授权绑定material_upload／material-upload:rongyao-operations单次票据。执行器必须继续核对同版源码、writer、当前飞书发布、依赖、scope锁、熔断、文件SHA与原账本；没有offline提交选项。

同名不同SHA、同文件不同归属、重复制作编号及后台同名但SHA未知都停止。selection_pending、submitted_pending、submission_unknown保留原job；新票据、换名称或换登录不解除受理未知。仅完整名称唯一匹配真实ID才listed；需补验详情沿原执行器只读回查，详情、播放、审核、广告发布分别验收。更换账号时旧账本不作为新账号成功证据，未独立核验仍为account_identity_verified=false。

## 诊断与维护（出现对应问题时）

DEPENDENCY_MISSING补实际缺项；WRITER_HOST_REQUIRED核对动作主机；版本不一致核对当前包，不绕过发布守卫。认证挑战、系统权限、平台拒绝及网络错误分别报告；阻塞记录只代表最后一次观察，不能当成当前实测。Chrome状态、一次auth recheck的条件、安全确认与旧验收范围见 [兼容与历史细则](references/cli-contract.md#兼容分支历史验收与维护细则)。

日常上传不重复登录/列表冒烟，不重打规则包、不维护云规则。明确维护时先保存原件、完成修改与相关验证，再按授权打包、发布和回读。安装、计划、隔离测试与历史单次入库均不替代本批验收。当前代码及发布合同中的版本为准，不靠主控内的旧版本叙述判定功能。
