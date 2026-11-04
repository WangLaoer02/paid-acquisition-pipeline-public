---
name: paid-skit-progressive-setup
description: 为买量短剧工作流或首条写轮眼案例配置Codex所需Skill和本机工具，按制作阶段安装、检查及续接；用于部署和迁移，不承担剧本、生成或工程制作。
---

# 买量短剧渐进安装（公开版安装器）

这是安装入口，不是第二个生产主控。业务规则仍读取[中心当前独立规则](https://example.invalid/receiver-feishu-document)，现场要求与项目表决定生产阶段；本包记录安装阶段，不能标业务完成。

公开版先按[公开安装汇总](references/public-install.md)运行 `setup`，逐项汇报文件、软件基础探测、实际运行和业务验收。国内即梦缺项不能以国际依赖替代。

首次只读[渐进安装与验收](references/progressive-setup.md)中的开始章节，运行`scripts/progressive_install.py verify`和当前阶段`plan`。只有安装被本次任务授权时才运行`install`；依赖安装用单独的`env-install`或`tool-install-feishu`。`doctor`只读，不登录、不下载模型、不打开浏览器、不触发生成。

进入阶段后才读相应业务Skill：安装器按manifest映射复制该阶段文件；源文件归档在ZIP内，尚未安装的下游不作为当前上下文展开。已有同名源文件不一致时整阶段拒绝覆盖，先逐文件核对，不为安装重置手改。

每一阶段使用 `setup --phases N` 汇总 `install → doctor`。退出 2 是未完成；退出 0 仍需独立核对实际运行与业务门。安装可用与账号、模型、原生PR打开、生成费用授权分开记录。没有回复、只有存在的二进制或只有静态模型表，不能标实际接口可用。

历史命令写死`~/.agents/skills`、`.system/imagegen`或旧机器目录时，先用安装器`path`定位实际安装文件。不要创建别人的旧绝对路径或复制账号配置。[来源与条件依赖](references/source-and-conditions.md)列明真实文件、原生工具、可选分支和不可用项；按触发条件查阅，不自动启用全部分支。

仅复现SK002已有素材时，可直接安装bootstrap和阶段6/7，按飞书手册下载案例包、标准库校验/重连，再PR原生检查与导出；无需安装语音模型或再次付费生成。

新Skill安装后在Codex下一轮对话可发现。先核对接收机器的目录与能力，再继续首次未通过的安装项；安装包不提供原生产会话或费用授权。


## 后台素材上传安装分支

当前同版WF20261103.1／V005.38。`--phase upload`安装rongyao-material-upload及荣耀工具9个同源Skill（含默认HTTP上传与短信只读认证依赖），属于原A15／接B05之后的独立专项，不是生产单选新节点。仅首次部署/版本或环境变化时核对工作区与Skill；普通上传已就绪时直接读rongyao-http-upload提交与恢复合同，不重复Skill check、入口探测或登录授权；需要独立Python环境时使用`env-install --profile upload`，仍不登录或上传。Skill安装不带项目Plan、媒体或凭据，缺已审输入保持阻塞；具体提交范围和未验证能力读Skill全文。

上传分支包含rongyao 0.2.3同源实现；通用计划经workspace／输入SHA票据、writer与scope保护。沿当前专项区分通用CLI和原固定Plan，真实新批次上传另验；不复制账号、状态或媒体。

本候选只供隔离目录安装与验证，不能取代当前正式发布。实际维护火影B库才按naruto-b-library阶段补入方法，库与维护工具仍独立配置核验。Seedance专项按需使用 seedance-specialists 阶段；工作台不是生产前置。

A04列物料需求，A05查原件与真缺口，A06仅补必要；无缺口沿用。无需为此安装phase3全套；需要三视图／角色目录／归档／选用图像工具时分别按asset-turnaround／asset-catalog／asset-archive／asset-image安装。
