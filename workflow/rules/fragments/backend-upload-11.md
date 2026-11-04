## 4. 提交、效率与纠错

### 通用成片默认HTTP

按 [HTTP最短路径](../../tools/rongyao-http-upload/SKILL.md#最短路径)逐项执行，复用原计划、原job及制作验收。计划/inspect-plan由同版operations完成，提交与回查由HTTP执行器完成；单次票据、writer、源码/文件SHA、锁、账本去重及当前发布守卫全部保留。submitted_pending不是完成，受理未知只回查，详情失败不重传。

### Chrome兼容CLI（仅用户明确选择）

读取operations的 [兼容提交合同](../implementation/rongyao-tools/skills/rongyao-operations/references/cli-contract.md#chrome兼容提交合同)。该分支完整保留独立登录、同版入口、全字段读回、选文件前selection_pending、单次提交和有限回查。HTTP失败不自动切换到此分支。

### 原生选框分支与恢复

本批明确采用原生辅助功能选框时，按需读取[原生选框与未知受理恢复](../implementation/backend-upload/skill/references/native-recovery.md)。使用发布的native-plan／native-upload，计划绑定实际执行器及本机构建SHA；项目内历史助手不用于续传。同目标两次无效跨进程保留，取消不算提交，未知受理保留真实原因且只回查。按Open最终提交前再次计算当前视频SHA，核对选框内唯一完整绝对路径、精确文件预览及当前全部表单字段；任一变化、缺失或歧义立即停止，未发出提交事件仍保留selection_pending和native_pre_submit_rejected证据。只有文件名而无完整路径不能证明是同一文件，不推断、双击或换接口提交。此分支的隔离守卫验证不等于真实新批次上传通过。


### 原固定Plan接口（仅明确续接原14条Plan时）

原Plan的私有安全输入、并行分片、完整归属反馈及恢复要求仅在本次明确续接该Plan时读[旧接口映射](../implementation/backend-upload/skill/references/mapping.md)对应章节。它们不是普通CLI上传前置；不能因新文件缺旧Plan或私有请求文件而停通用CLI，不主动索取Cookie或再次询问登录授权。

